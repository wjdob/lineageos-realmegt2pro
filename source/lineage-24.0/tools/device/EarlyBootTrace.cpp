// Temporary arm64 diagnostic init wrapper. Never part of a release image.
// PID1 immediately executes the byte-identical saved first-stage init. A child
// reads kernel messages, bounded to 2 MiB and 120 seconds. It creates exactly one
// new 0600 log on the ext4 metadata filesystem, after confirming that mount via
// PID1's root. It never opens a block device, credential, calibration or data file.
// --self-test only checks syscall/clock/kmsg access; it creates no file or child.
#if !defined(__aarch64__)
#error Linux arm64 only
#endif
static long Sys(long n,long a=0,long b=0,long c=0,long d=0,long e=0) {
  register long x8 asm("x8")=n;
  register long x0 asm("x0")=a;
  register long x1 asm("x1")=b;
  register long x2 asm("x2")=c;
  register long x3 asm("x3")=d;
  register long x4 asm("x4")=e;
  asm volatile("svc 0":"+r"(x0):"r"(x8),"r"(x1),"r"(x2),"r"(x3),"r"(x4):"memory","cc");
  return x0;
}
static long Ptr(const void* p) {return reinterpret_cast<long>(p);}
static bool Equal(const char* a,const char* b) {
  while(*a && *a==*b){++a;++b;} return *a==*b;
}
static bool Contains(const char* text,long size,const char* needle) {
  for(long i=0;i<size;++i){long j=0;while(needle[j] && i+j<size && text[i+j]==needle[j])++j;if(!needle[j])return true;}return false;
}
[[noreturn]] static void End(long status) {Sys(93,status);__builtin_unreachable();}
static long Open(const char* path,long flags,long mode=0) {return Sys(56,-100,Ptr(path),flags,mode);}
struct Time {long sec,nsec;};
static long Seconds() {Time t; if(Sys(113,1,Ptr(&t)))return -1;return t.sec;}
static void Pause() {Time t{0,20000000};Sys(101,Ptr(&t));}
static bool WriteAll(long fd,const char* p,long size) {
  while(size>0){long n=Sys(64,fd,Ptr(p),size);if(n==-4)continue;if(n<=0)return false;p+=n;size-=n;}return true;
}
[[noreturn]] static void Capture() {
  constexpr long limit=2*1024*1024;
  static char buffer[limit];
  static char mountinfo[65536];
  static long fsinfo[32]; // statfs arm64 UAPI, deliberately overallocated.
  const long begin=Seconds();if(begin<0)End(2);
  long input=-1,output=-1,proc=-1,used=0,sent=0,last_sync=begin;
  while(Seconds()-begin<120 && used<limit) {
    if(input<0)input=Open("/dev/kmsg",0x80800); // RDONLY|NONBLOCK|CLOEXEC.
    if(proc<0) {
      proc=Open("/proc",0x90000); // Hold the actual proc mount across switch_root.
      if(proc>=0 && (Sys(44,proc,Ptr(fsinfo)) || fsinfo[0]!=0x9fa0)){Sys(57,proc);proc=-1;}
    }
    if(output<0 && proc>=0) {
      long info=Sys(56,proc,Ptr("1/mountinfo"),0x80000);
      long bytes=info>=0?Sys(63,info,Ptr(mountinfo),sizeof(mountinfo)):0;
      if(info>=0)Sys(57,info);
      if(bytes>0 && Contains(mountinfo,bytes," /metadata ")) {
        long dir=Sys(56,proc,Ptr("1/root/metadata"),0x90000);
        if(dir>=0) {
          if(Sys(44,dir,Ptr(fsinfo))==0 && fsinfo[0]==0xef53) {
            // New file only, final symlink refused, existing logs never overwritten.
            output=Sys(56,dir,Ptr("lineage17-earlyboot-01.log"),0xa00c1,0600);
          }
          Sys(57,dir);
          if(output==-17)End(3); // EEXIST.
        }
      }
    }
    if(input>=0) {
      long available=limit-used;if(available>8192)available=8192;
      long n=Sys(63,input,Ptr(buffer+used),available);
      if(n>0)used+=n;
      else if(n!=-11 && n!=-32 && n!=-4)break; // EAGAIN/EPIPE/EINTR.
    }
    if(output>=0 && used>sent) {
      if(!WriteAll(output,buffer+sent,used-sent))break;
      sent=used;
      const long now=Seconds();
      if(now-last_sync>=1){Sys(82,output);last_sync=now;}
    }
    Pause();
  }
  if(output>=0){Sys(82,output);Sys(57,output);}
  if(input>=0)Sys(57,input);
  if(proc>=0)Sys(57,proc);
  End(0);
}
extern "C" [[noreturn]] void Start(long* stack) {
  const long argc=stack[0];char** argv=reinterpret_cast<char**>(stack+1);
  char** env=reinterpret_cast<char**>(stack+argc+2);
  if(argc==2 && Equal(argv[1],"--self-test")) {
    long fd=Open("/dev/kmsg",0x80800);
    if(fd<0 || Seconds()<0)End(1);
    Sys(57,fd);
    constexpr char msg[]="earlyboot-clock-kmsg-self-test-ok; no file created\n";
    WriteAll(1,msg,sizeof(msg)-1);End(0);
  }
  if(Sys(172)!=1)End(4); // Never launch init from an ordinary shell.
  if(Sys(220,17,0,0,0,0)==0)Capture(); // clone(SIGCHLD), child only.
  Sys(221,Ptr("/init.lineage-original"),Ptr(argv),Ptr(env));
  // Executing the saved init is mandatory. PID1 must not pretend success.
  End(127);
}
extern "C" __attribute__((naked,noreturn)) void _start() {
  asm volatile("mov x0, sp\nbl Start\n");
}
