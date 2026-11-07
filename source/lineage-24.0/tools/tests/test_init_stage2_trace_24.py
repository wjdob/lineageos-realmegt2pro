"""Compile the actual RAM-copy and stage2 logger, with filesystem calls mocked."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'build'))
from init_boot_trace_24 import HEADER, STAGE2_HEADER


@unittest.skipUnless(shutil.which('c++'), 'host C++ compiler unavailable')
class Stage2Trace(unittest.TestCase):
    def compile_and_run(self, source, cases):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'android-base').mkdir()
            (root/'android-base/logging.h').write_text('''#pragma once
namespace android { namespace base {
enum LogId { MAIN }; enum LogSeverity { INFO, FATAL };
inline void KernelLogger(LogId, LogSeverity, const char*, const char*, unsigned, const char*) {}
} }
''')
            (root/'trace.h').write_text(HEADER+STAGE2_HEADER)
            (root/'test.cpp').write_text(source)
            result=subprocess.run(['c++','-std=c++17','-I',str(root),str(root/'test.cpp'),'-o',str(root/'test')],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            for case in cases:
                with self.subTest(case=case):
                    result=subprocess.run([str(root/'test'),case],capture_output=True)
                    self.assertEqual(result.returncode,0,result.stderr.decode())

    def test_ram_copy_is_bounded_exclusive_and_closes_failures(self):
        self.compile_and_run(r'''
#include <algorithm>
#include <fcntl.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cassert>
#include <string>
#include <cerrno>
static std::string mode, output;
static size_t copied=0;
static int source_closes=0,target_closes=0,creates=0;
static int mounts=0;
static int Open(const char* path,int flags,unsigned permissions=0) {
 if(std::string(path)=="/lineage-stage2-init") {
   assert(flags==(O_RDONLY|O_NOFOLLOW|O_CLOEXEC)); return mode=="no-source" ? -1 : 100;
 }
 assert(std::string(path)=="/dev/lineage-stage2-init");
 assert(flags==(O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC));
 assert(permissions==0750); ++creates; return mode=="exists" ? -1 : 101;
}
static int Stat(int fd,struct stat* info) {
 assert(fd==100); info->st_mode=S_IFREG|0750;info->st_uid=0;
 info->st_size=mode=="oversized" ? 9*1024*1024 : 4096;return 0;
}
static ssize_t Read(int fd,void* data,size_t size) {
 assert(fd==100);size=std::min(size,4096-copied);
 std::fill_n(static_cast<char*>(data),size,'x');copied+=size;return size;
}
static ssize_t Write(int fd,const void* data,size_t size) {
 assert(fd==101);if(mode=="write-fails") return -1;
 size=std::min(size,size_t(73)); output.append(static_cast<const char*>(data),size);return size;
}
static int Close(int fd) { if(fd==100) ++source_closes;else {assert(fd==101);++target_closes;} return 0; }
static int Mount(const char* source,const char* target,const char*,unsigned long flags,const void*) {
 assert(std::string(target)=="/system/bin/init");++mounts;
 if(mounts==1) assert(source && std::string(source)=="/dev/lineage-stage2-init" && flags==4096);
 else assert(source==nullptr && flags==(4096|32|4));return 0;
}
#define open(...) Open(__VA_ARGS__)
#define fstat(...) Stat(__VA_ARGS__)
#define read(...) Read(__VA_ARGS__)
#define write(...) Write(__VA_ARGS__)
#define close(...) Close(__VA_ARGS__)
#define mount(...) Mount(__VA_ARGS__)
#define FIRST_STAGE_INIT 1
#include "trace.h"
int main(int argc,char** argv) {
 assert(argc==2);mode=argv[1];
 if(mode=="recovery") {
   assert(android::init::LineageCopyStage2ToRam(false));
   assert(android::init::LineageBindStage2FromRam(false));
   android::init::LineageCaptureLoaderStderr(false);
   assert(creates==0 && source_closes==0 && target_closes==0 && mounts==0 && copied==0);return 0;
 }
 bool good=android::init::LineageCopyStage2ToRam(true);
 assert(good==(mode=="good"));
 if(good) {
   assert(output==std::string(4096,'x') && source_closes==1 && target_closes==1);
   assert(android::init::LineageBindStage2FromRam(true) && mounts==2);
 }
 else if(mode=="no-source") assert(creates==0 && source_closes==0 && target_closes==0);
 else if(mode=="oversized") assert(creates==0 && source_closes==1 && target_closes==0);
 else if(mode=="exists") assert(source_closes==1 && target_closes==0);
 else assert(source_closes==1 && target_closes==1);
}
''',('good','no-source','oversized','exists','write-fails','recovery'))

    def test_stage2_append_checks_owner_type_mode_cap_and_errno(self):
        self.compile_and_run(r'''
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cassert>
#include <string>
#include <cerrno>
static std::string mode, output="earlier exec\n";
static int opens=0,closes=0,writes=0,seeks=0;
static size_t position=0;
static int Open(const char* path,int flags,unsigned permissions=0) {
 assert(std::string(path)=="/metadata/lineage17-stage2-trace-09.log");
 assert(flags==(O_WRONLY|O_CREAT|O_NOFOLLOW|O_CLOEXEC));assert(permissions==0600);
 ++opens;return 43;
}
static int Stat(int fd,struct stat* info) {
 assert(fd==43);info->st_mode=(mode=="wrong-type" ? S_IFLNK : S_IFREG)|0600;
 info->st_uid=mode=="wrong-owner" ? 2000 : 0;info->st_nlink=1;info->st_size=output.size();return 0;
}
static ssize_t Write(int fd,const void* data,size_t size) {
 assert(fd==43);++writes;if(mode=="interrupted" && writes==1) {errno=EINTR;return -1;}
 if(output.size()<position+size) output.resize(position+size);
 output.replace(position,size,static_cast<const char*>(data),size);position+=size;return size;
}
static off_t Seek(int fd,off_t offset,int whence) {assert(fd==43 && offset==0 && whence==SEEK_END);++seeks;position=output.size();return position;}
static int Sync(int fd) {assert(fd==43);return 0;}
static int Close(int fd) {assert(fd==43);++closes;return 0;}
#define open(...) Open(__VA_ARGS__)
#define fstat(...) Stat(__VA_ARGS__)
#define write(...) Write(__VA_ARGS__)
#define fsync(...) Sync(__VA_ARGS__)
#define close(...) Close(__VA_ARGS__)
#define lseek(...) Seek(__VA_ARGS__)
#include "trace.h"
static void Log(const char* message) {
 errno=E2BIG;android::init::LineageSecondStageTrace(android::base::MAIN,android::base::INFO,"init","test",1,message);assert(errno==E2BIG);
}
int main(int argc,char** argv) {
 assert(argc==2);mode=argv[1];Log("selinux_setup entry");Log("before Android policy load");
 assert(opens==1);
 if(mode=="wrong-type" || mode=="wrong-owner") assert(output=="earlier exec\n" && closes==1 && writes==0 && seeks==0);
 else {
   assert(output.find("earlier exec\n")==0 && output.find("before Android policy load")!=std::string::npos);
   std::string large(3*1024*1024,'x');Log(large.c_str());Log("after cap");
   assert(output.size()==2*1024*1024 && opens==1 && closes==1 && seeks==3);
 }
}
''',('good','wrong-type','wrong-owner','interrupted'))

    def test_kernel_capture_parent_and_recovery_paths(self):
        self.compile_and_run(r'''
#include <fcntl.h>
#include <sys/types.h>
#include <unistd.h>
#include <cassert>
#include <cerrno>
#include <string>
static std::string scenario;
static int opens=0,closes=0,forks=0;
static int Open(const char* path,int flags,unsigned mode=0) {
 ++opens;
 if(opens==1) {
   assert(std::string(path)=="/dev/kmsg" && flags==(O_RDONLY|O_NONBLOCK|O_CLOEXEC));
   if(scenario=="input-fails") {errno=EACCES;return -1;} return 40;
 }
 assert(std::string(path)=="/metadata/lineage17-kmsg-trace-09.log");
 assert(flags==(O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC) && mode==0600);
 if(scenario=="output-exists") {errno=EEXIST;return -1;} return 41;
}
static int Close(int fd) {assert(fd==40 || fd==41);++closes;return 0;}
static pid_t Fork() {++forks;if(scenario=="fork-fails") {errno=EAGAIN;return -1;} return 123;}
#define open(...) Open(__VA_ARGS__)
#define close(...) Close(__VA_ARGS__)
#define fork() Fork()
#include "trace.h"
int main(int argc,char** argv) {
 assert(argc==2);scenario=argv[1];
 assert(android::init::LineageStartKernelCapture(false)==0 && opens==0 && forks==0);
 int result=android::init::LineageStartKernelCapture(true);
 if(scenario=="input-fails") assert(result==-EACCES && opens==1 && closes==0 && forks==0);
 else if(scenario=="output-exists") assert(result==-EEXIST && opens==2 && closes==1 && forks==0);
 else assert(result==(scenario=="fork-fails" ? -EAGAIN : 123) && opens==2 && closes==2 && forks==1);
}
''',('good','input-fails','output-exists','fork-fails'))

    def test_loader_capture_is_normal_only_exclusive_and_synchronous(self):
        self.compile_and_run(r'''
#include <fcntl.h>
#include <unistd.h>
#include <cassert>
#include <string>
static std::string scenario;
static int opens=0,duplicates=0,syncs=0,closes=0;
static int Open(const char* path,int flags,unsigned mode=0) {
 assert(std::string(path)=="/metadata/lineage17-stage2-loader-09.log");
 assert(flags==(O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC|O_SYNC));assert(mode==0600);
 ++opens;return scenario=="exists" ? -1 : 45;
}
static int Dup(int oldfd,int newfd) {assert(oldfd==45 && (newfd==1 || newfd==2));++duplicates;return newfd;}
static int Sync(int fd) {assert(fd==45);++syncs;return 0;}
static int Close(int fd) {assert(fd==45);++closes;return 0;}
#define open(...) Open(__VA_ARGS__)
#define dup2(...) Dup(__VA_ARGS__)
#define fsync(...) Sync(__VA_ARGS__)
#define close(...) Close(__VA_ARGS__)
#define FIRST_STAGE_INIT 1
#include "trace.h"
int main(int argc,char** argv) {
 assert(argc==2);scenario=argv[1];
 android::init::LineageCaptureLoaderStderr(false);
 assert(opens==0 && duplicates==0 && syncs==0 && closes==0);
 android::init::LineageCaptureLoaderStderr(true);
 assert(opens==1);
 if(scenario=="exists") assert(duplicates==0 && syncs==0 && closes==0);
 else assert(duplicates==2 && syncs==1 && closes==1);
}
''',('good','exists'))


if __name__=='__main__':unittest.main()
