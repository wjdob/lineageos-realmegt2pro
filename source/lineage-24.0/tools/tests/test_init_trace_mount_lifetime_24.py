"""Exercise actual fatal-only logger with zero normal-path filesystem I/O."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from init_boot_trace_24 import HEADER


class InitTraceMountLifetime(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'), 'host C++ compiler unavailable')
    def test_normal_path_and_fatal_dump_lifetimes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'android-base').mkdir()
            (root/'android-base/logging.h').write_text('''#pragma once
namespace android { namespace base {
enum LogId { MAIN }; enum LogSeverity { INFO, FATAL };
inline void KernelLogger(LogId, LogSeverity, const char*, const char*, unsigned, const char*) {}
} }
''')
            (root/'trace.h').write_text(HEADER)
            (root/'test.cpp').write_text(r'''
#include <fcntl.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <unistd.h>
#include <cerrno>
#include <cassert>
#include <string>
static int opens = 0;
static int mounts = 0;
static int unmounts = 0;
static int closes = 0;
static int stats = 0;
static bool mounted = false;
static std::string scenario;
static std::string captured;
static int FakeStatfs(const char*, struct statfs* info) {
  ++stats; info->f_type = scenario == "existing" ? 0xef53 : 0; return 0;
}
static int FakeMkdir(const char*, unsigned mode) { assert(mode==0700); return 0; }
static int FakeMount(const char* source, const char*, const char* type, unsigned long flags, const void*) {
  assert(std::string(source)=="/dev/block/by-name/metadata");
  assert(std::string(type)=="ext4");
  assert(flags==(MS_NODEV|MS_NOSUID|MS_NOEXEC|MS_NOATIME));
  ++mounts; if(scenario=="mount-fails") return -1; mounted=true; return 0;
}
static int FakeUnmount(const char*) {
  assert(mounted && (opens==0 || closes==1 || scenario=="file-exists")); mounted=false; ++unmounts; return 0;
}
static int FakeOpen(const char* path, int flags, unsigned mode) {
  assert((flags & (O_EXCL|O_NOFOLLOW|O_CLOEXEC)) == (O_EXCL|O_NOFOLLOW|O_CLOEXEC));
  assert(std::string(path).find("lineage17-init-trace-09.log")!=std::string::npos);
  assert(mode == 0600); ++opens;
  if(scenario=="file-exists") {errno=EEXIST; return -1;}
  return 42;
}
static ssize_t FakeWrite(int fd, const void* data, size_t size) {
  assert(fd == 42); captured.append(static_cast<const char*>(data), size); return size;
}
static int FakeSync(int fd) { assert(fd == 42); return 0; }
static int FakeClose(int fd) { assert(fd==42); ++closes; return 0; }
#define statfs(...) FakeStatfs(__VA_ARGS__)
#define mkdir(...) FakeMkdir(__VA_ARGS__)
#define mount(...) FakeMount(__VA_ARGS__)
#define umount(...) FakeUnmount(__VA_ARGS__)
#define open(...) FakeOpen(__VA_ARGS__)
#define write(...) FakeWrite(__VA_ARGS__)
#define fsync(...) FakeSync(__VA_ARGS__)
#define close(...) FakeClose(__VA_ARGS__)
#include "trace.h"
static void Log(const char* msg, android::base::LogSeverity severity=android::base::INFO) {
  errno = E2BIG;
  android::init::LineageFirstStageTrace(android::base::MAIN, severity, "init", "test", 1, msg);
  assert(errno == E2BIG);
}
int main(int argc, char** argv) {
  assert(argc==2); scenario=argv[1];
  Log("check_fs temporary mount succeeded");
  Log("check_fs probe unmounted; fsck done");
  Log("normal SAR pivot and metadata mount");
  assert(opens==0 && mounts==0 && stats==0 && captured.empty());
  if(scenario=="checkpoint") {
    Log("LINEAGE_INIT_TRACE normal final metadata mounted");
    assert(opens==1 && mounts==0 && stats==0 && closes==0);
    assert(captured.find("temporary mount succeeded")!=std::string::npos);
    Log("LINEAGE_INIT_TRACE first-stage exec selinux_setup");
    assert(captured.find("exec selinux_setup")!=std::string::npos);
    std::string chunk(128*1024, 'x');
    for(int i=0;i<24;++i) Log(chunk.c_str());
    assert(captured.size()==2*1024*1024);
    assert(opens==1 && mounts==0 && stats==0 && closes==0); return 0;
  }
  std::string large(3 * 1024 * 1024, 'x'); Log(large.c_str());
  if(scenario=="signal") Log("InitFatalReboot: signal 6");
  else Log("Failed to mount required partitions early", android::base::FATAL);
  assert(stats==1 && !mounted);
  if(scenario=="mount-fails") assert(opens==0 && captured.empty() && unmounts==0);
  else if(scenario=="file-exists") assert(opens==1 && closes==0 && captured.empty() && unmounts==1);
  else {
    assert(opens==1 && closes==1 && captured.size()<=256*1024);
    assert(captured.find("temporary mount succeeded")!=std::string::npos);
    assert(captured.find("normal SAR pivot")!=std::string::npos);
    assert(unmounts==(scenario=="existing" ? 0 : 1));
  }
  Log("InitFatalReboot: signal 6"); assert(stats==1); // Never retry/overwrite.
}
''')
            subprocess.run(['c++', '-std=c++17', '-I', str(root), str(root/'test.cpp'), '-o', str(root/'test')], check=True, capture_output=True)
            for scenario in ('existing', 'private', 'mount-fails', 'file-exists', 'signal', 'checkpoint'):
                with self.subTest(scenario=scenario):
                    subprocess.run([str(root/'test'), scenario], check=True, capture_output=True)


if __name__ == '__main__': unittest.main()
