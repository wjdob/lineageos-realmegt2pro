// First Android17 trial: test the retained recovery's read-only NVBK fsync path.
// Linux arm64 UAPI: asm-generic/unistd.h and linux/fs.h. No libc dependency.
// The sole device open is O_RDONLY. Require a20MiB block device and kernel RO=1.
// The only write syscall targets stdout; no device content is read or written.
#if !defined(__aarch64__)
#error This diagnostic requires Linux arm64.
#endif

static long Call(long number, long a=0, long b=0, long c=0) {
  register long x8 asm("x8")=number;
  register long x0 asm("x0")=a;
  register long x1 asm("x1")=b;
  register long x2 asm("x2")=c;
  register long x3 asm("x3")=0;
  asm volatile("svc 0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3) : "memory", "cc");
  return x0;
}

[[noreturn]] static void Finish(const char* message, long bytes, long status) {
  Call(64,1,reinterpret_cast<long>(message),bytes); // write stdout only
  Call(93,status); // exit
  __builtin_unreachable();
}

extern "C" [[noreturn]] void _start() {
  static constexpr char path[]="/dev/block/by-name/oplusstanvbk_a";
  const long fd=Call(56,-100,reinterpret_cast<long>(path),0x80000); // openat, O_RDONLY|O_CLOEXEC
  if (fd<0) Finish("open-readonly-failed\n",21,1);
  unsigned long bytes=0;
  int read_only=-1;
  if (Call(29,fd,0x80081272,reinterpret_cast<long>(&bytes)) || bytes!=20UL*1024*1024)
    Finish("wrong-block-size\n",17,2); // BLKGETSIZE64
  if (Call(29,fd,0x125e,reinterpret_cast<long>(&read_only)) || read_only!=1)
    Finish("kernel-readonly-required\n",25,3); // BLKROGET
  if (Call(82,fd)) Finish("readonly-fsync-failed\n",22,4);
  if (Call(57,fd)) Finish("close-failed\n",13,5);
  Finish("readonly-size-ro-fsync-ok\n",26,0);
}
