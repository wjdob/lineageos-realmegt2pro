// Private recovery probe only: set flags on one already-mounted RAM file.
// No arguments, block devices, filesystem creation, policy or service changes.
// Linux arm64 UAPI: geteuid175, statfs43, mount40, write64, exit93.
#if !defined(__aarch64__)
#error Linux arm64 required
#endif
static long Call(long number,long a=0,long b=0,long c=0,long d=0,long e=0) {
  register long x8 asm("x8")=number;
  register long x0 asm("x0")=a;
  register long x1 asm("x1")=b;
  register long x2 asm("x2")=c;
  register long x3 asm("x3")=d;
  register long x4 asm("x4")=e;
  asm volatile("svc 0" : "+r"(x0) : "r"(x8),"r"(x1),"r"(x2),"r"(x3),"r"(x4) : "memory","cc");
  return x0;
}
template<unsigned N> [[noreturn]] static void Finish(const char (&text)[N],long code) {
  Call(64,1,reinterpret_cast<long>(text),N-1);Call(93,code);__builtin_unreachable();
}
extern "C" [[noreturn]] void _start() {
  static constexpr char target[]="/mnt/lineage17-stage2-bind-probe-07/system/bin/init";
  if(Call(175)!=0) Finish("root-required\n",1);
  unsigned long info[32]={};
  if(Call(43,reinterpret_cast<long>(target),reinterpret_cast<long>(info)) || info[0]!=0x01021994)
    Finish("private-target-must-be-tmpfs\n",2);
  // MS_BIND|MS_REMOUNT|MS_NODEV: only this file bind, executable and not nosuid.
  if(Call(40,0,reinterpret_cast<long>(target),0,0x1024,0)) Finish("ram-bind-remount-failed\n",3);
  Finish("ram-bind-flags-ok\n",0);
}
