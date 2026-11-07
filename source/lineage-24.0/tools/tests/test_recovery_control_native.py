"""Execute the actual C controller with controlled syscall boundaries on Linux."""
from pathlib import Path
import os,shutil,subprocess,tempfile,unittest

class RecoveryControlNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('gcc'):raise unittest.SkipTest('host gcc unavailable')
        cls.temp=tempfile.TemporaryDirectory();root=Path(cls.temp.name);cls.root=root
        (root/'sys').mkdir();(root/'empty').mkdir();(root/'busy').mkdir();(root/'busy/123').touch();(root/'mapped').mkdir();(root/'mapped/dm-1').touch()
        (root/'sys/system_properties.h').write_text('#define PROP_VALUE_MAX 92\nint __system_property_get(const char*,char*);\n')
        source=Path(__file__).resolve().parents[1]/'device/recovery_control.c'
        fixture=root/'fixture.c'
        fixture.write_text(r'''
#define _GNU_SOURCE
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <mntent.h>
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int ismounted,mountpoint_created;
static int scenario(const char *s){return !strcmp(getenv("CASE"),s);}
int __system_property_get(const char *key,char *value){
 const char *v="";
 if(!strcmp(key,"ro.bootmode"))v=scenario("android")?"normal":"recovery";
 if(!strcmp(key,"ro.product.model"))v=scenario("wrong-model")?"OTHER":"RMX3301";
 if(!strcmp(key,"ro.build.version.sdk"))v=scenario("api36")?"36":"37";
 if(!strcmp(key,"ro.lineage.recovery.engineering"))v=scenario("production")?"":"1";
 if(!strcmp(key,"ro.adb.secure"))v=scenario("insecure")?"0":"1";
 if(!strcmp(key,"ro.adb.secure.recovery"))v=scenario("insecure-recovery")?"0":"1";
 if(!strcmp(key,"ro.boot.slot_suffix"))v=scenario("slot")?"_x":"_a";
 if(!strcmp(key,"ro.boot.vbmeta.device_state"))v=scenario("locked")?"locked":"unlocked";
 strcpy(value,v);return strlen(v);
}
static int mock_uid(void){return scenario("nonroot")?2000:0;}
static int mock_open(const char *p,int flags,...){(void)flags;return strstr(p,"misc")?42:43;}
static int mock_close(int fd){(void)fd;return 0;}
static int mock_flock(int fd,int op){(void)fd;(void)op;return scenario("control-busy")?-1:0;}
static ssize_t mock_pread(int fd,void *p,size_t n,off_t off){
 (void)fd;unsigned char b[]={2,176,10,116,86,0,0};
 if(n!=7||off!=32768)return -1;
 if(scenario("vab"))b[5]=1;memcpy(p,b,7);return scenario("short-misc")?6:7;
}
static DIR *mock_opendir(const char *path){
 char p[4096];const char *part="empty";
 if(!strcmp(path,"/proc")&&scenario("installer-busy"))part="busy";
 if(!strcmp(path,"/sys/class/block")&&scenario("mappings"))part="mapped";
 snprintf(p,sizeof(p),"%s/%s",getenv("FIXTURE"),part);return opendir(p);
}
static FILE *mock_mounts(const char *p,const char *mode){
 (void)p;(void)mode;
 static char empty[]="",ro[]="/dev/block/dm-1 /mnt/system ext4 ro 0 0\n",rw[]="/dev/block/dm-1 /mnt/system ext4 rw 0 0\n";
 char *s=scenario("rw-mount")?rw:(ismounted||scenario("mounted"))?ro:empty;
 return fmemopen(s,strlen(s),"r");
}
static FILE *mock_fopen(const char *p,const char *mode){
 (void)mode;static char busy[]="update_engine_s\n",identity[]="system_a\n",wrong[]="system_b\n";
 char *s=strstr(p,"/comm")?busy:scenario("wrong-dm")?wrong:identity;
 return fmemopen(s,strlen(s),"r");
}
static int mock_stat(const char *p,struct stat *st){
 (void)p;if(scenario("no-mapping"))return -1;memset(st,0,sizeof(*st));st->st_mode=S_IFBLK;st->st_rdev=5;return 0;
}
static int mock_lstat(const char *p,struct stat *st){
 if(!strcmp(p,"/mnt/system")&&!mountpoint_created&&(scenario("missing-mountpoint")||scenario("mountpoint-parent-link")||scenario("mkdir-failure"))){errno=ENOENT;return -1;}
 memset(st,0,sizeof(*st));st->st_mode=scenario("mountpoint-link")||scenario("mountpoint-parent-link")?S_IFLNK:S_IFDIR;return 0;
}
static int mock_mkdir(const char *p,mode_t mode){
 if(strcmp(p,"/mnt/system")||mode!=0755)abort();
 if(scenario("mkdir-failure")){errno=EACCES;return -1;}
 mountpoint_created=1;puts("MKDIR_RAM");return 0;
}
static char *mock_realpath(const char *p,char *out){(void)p;strcpy(out,"/dev/block/dm-1");return out;}
static int mock_mount(const char *dev,const char *target,const char *type,unsigned long flags,const void *data){
 if(strcmp(dev,"/dev/block/mapper/system_a")||strcmp(target,"/mnt/system")||strcmp(type,"ext4")||
    flags!=(MS_RDONLY|MS_NODEV|MS_NOSUID)||strcmp(data,"noload"))abort();
 puts("MOUNT_RO_NOLOAD");ismounted=1;return scenario("mount-failure")?-1:0;
}
static int mock_umount(const char *p){if(strcmp(p,"/mnt/system"))abort();puts("UNMOUNT");ismounted=0;return 0;}
static int mock_socket(int domain,int type,int protocol){
 if(domain!=AF_UNIX||type!=(SOCK_STREAM|SOCK_CLOEXEC)||protocol)abort();return 44;
}
static int mock_connect(int fd,const struct sockaddr *a,socklen_t n){
 (void)fd;if(n!=sizeof(struct sockaddr_un)||strcmp(((const struct sockaddr_un *)a)->sun_path,"/dev/socket/recovery"))abort();
 return scenario("socket-failure")?-1:0;
}
static ssize_t mock_send(int fd,const void *p,size_t n,int flags){
 (void)fd;if(n!=1||memcmp(p,"s",1)||flags!=MSG_NOSIGNAL)abort();puts("SIDELOAD_S");return 1;
}
#define getuid mock_uid
#define open mock_open
#define close mock_close
#define flock mock_flock
#define pread mock_pread
#define opendir mock_opendir
#define setmntent mock_mounts
#define fopen mock_fopen
#define stat(...) mock_stat(__VA_ARGS__)
#define lstat mock_lstat
#define mkdir mock_mkdir
#define realpath mock_realpath
#define mount mock_mount
#define umount mock_umount
#define socket mock_socket
#define connect mock_connect
#define send mock_send
'''+'\n#include "'+str(source)+'"\n')
        cls.binary=root/'control'
        result=subprocess.run(['gcc','-std=c11','-I'+str(root),str(fixture),'-o',str(cls.binary)],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def invoke(self,case,operation):
        return subprocess.run([str(self.binary),operation],env=dict(os.environ,CASE=case,FIXTURE=str(self.root)),capture_output=True,text=True)

    def test_wrong_identity_auth_slot_and_snapshot_stop_before_operations(self):
        for case in ('android','wrong-model','api36','production','insecure','insecure-recovery','slot','locked','nonroot','vab','short-misc','control-busy','installer-busy','rw-mount'):
            with self.subTest(case=case):
                p=self.invoke(case,'sideload-addon');self.assertNotEqual(p.returncode,0,p.stdout)
                self.assertNotIn('SIDELOAD_S',p.stdout);self.assertNotIn('MOUNT_RO',p.stdout)

    def test_exact_socket_protocol_and_ota_mapping_refusal(self):
        for operation in ('sideload-addon','sideload-ota'):
            p=self.invoke('normal',operation);self.assertEqual(p.returncode,0,p.stderr);self.assertIn('SIDELOAD_S',p.stdout)
        self.assertNotEqual(self.invoke('mappings','sideload-ota').returncode,0)
        self.assertEqual(self.invoke('mappings','sideload-addon').returncode,0)
        self.assertNotEqual(self.invoke('socket-failure','sideload-addon').returncode,0)

    def test_read_only_mount_and_identity_boundaries(self):
        p=self.invoke('normal','mount-system-ro');self.assertEqual(p.returncode,0,p.stderr);self.assertIn('MOUNT_RO_NOLOAD',p.stdout)
        for case in ('wrong-dm','no-mapping','mountpoint-link','mount-failure'):
            with self.subTest(case=case):self.assertNotEqual(self.invoke(case,'mount-system-ro').returncode,0)
        self.assertNotIn('MOUNT_RO',self.invoke('mounted','mount-system-ro').stdout)
        self.assertEqual(self.invoke('normal','unmount-system').returncode,0)

    def test_unknown_operation_has_no_effect(self):
        p=self.invoke('normal','erase');self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,'')

    def test_missing_packaged_mountpoint_is_created_only_under_real_ram_parent(self):
        p=self.invoke('missing-mountpoint','mount-system-ro');self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('MKDIR_RAM',p.stdout);self.assertIn('MOUNT_RO_NOLOAD',p.stdout)
        for case in ('mountpoint-parent-link','mkdir-failure'):
            with self.subTest(case=case):
                p=self.invoke(case,'mount-system-ro');self.assertNotEqual(p.returncode,0)
                self.assertNotIn('MOUNT_RO_NOLOAD',p.stdout)

if __name__=='__main__':unittest.main()
