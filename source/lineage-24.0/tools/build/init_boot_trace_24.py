"""Apply an explicitly selected RAM-only diagnostic init pair in an isolated tree.

This does not modify the release recipe or normal mount sequence. It buffers
first-stage messages before the normal final metadata mount, then records
progress without reordering mounts. An error-only dump handles earlier aborts.
"""
import argparse
import hashlib
import json
from pathlib import Path

from apply_recipe import isolated, safe_file

PREIMAGES = {
    'system/core/init/first_stage_mount.cpp': 'c4ca7f2e3d7f43e6c33d3112305427b18ce6c76d7818acf98e2204d9fd6acb38',
    'system/core/init/util.cpp': 'd692940f4954c4ed71246e1de0f9beefd9e2d45b2895b8d34375f94e4d3659c8',
    'system/core/init/first_stage_init.cpp': 'ddb34b37d470ad8266150865513ed25cbf29e1d404e248022765fbb1d9bc3b31',
    'system/core/init/selinux.cpp': 'fe0c79ed657ff7cffbde0026cebd0f741b2b5703dbd092d2e19b2df52b5a139e',
    'system/core/init/init.cpp': '4070fb5640a42fcd24d1d4b6cb88981b4648be5c9135e984e88800e345bf4f3b',
}

HEADER = r'''// Temporary first-stage diagnostic only; never selected for an OTA.
#pragma once
#include <android-base/logging.h>
#include <algorithm>
#include <cerrno>
#include <fcntl.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <unistd.h>
#include <string>

namespace android { namespace init {
inline void LineageFirstStageTrace(android::base::LogId id,
        android::base::LogSeverity severity, const char* tag, const char* file,
        unsigned int line, const char* message) {
    struct RestoreErrno { int value; ~RestoreErrno() { errno = value; } } restore { errno };
    android::base::KernelLogger(id, severity, tag, file, line, message);
    static bool dumped = false;
    static bool armed = false;
    static bool progress_refused = false;
    static int progress_fd = -1;
    static size_t written = 0;
    static auto* pending = new std::string;
    constexpr size_t limit = 256 * 1024;
    std::string entry = std::string(tag ? tag : "init") + ": " + message + "\n";
    if (pending->size() + entry.size() <= limit) *pending += entry;
    // This marker follows the ORIGINAL successful final metadata mount. No
    // file is opened during its temporary check_fs probe. On this device the
    // normal metadata mount precedes logical mapping and SAR pivot.
    if (std::string(message) == "LINEAGE_INIT_TRACE normal final metadata mounted") armed = true;
    if (armed) {
        if (progress_refused || written >= 2*1024*1024) return;
        if (progress_fd < 0) {
            progress_fd = open("/metadata/lineage17-init-trace-09.log",
                O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC, 0600);
            if (progress_fd < 0) { progress_refused = true; return; }
        }
        size_t remaining = std::min(pending->size(), 2*1024*1024-written);
        const char* data = pending->data();
        while (remaining) {
            ssize_t bytes = write(progress_fd, data, remaining);
            if (bytes < 0 && errno == EINTR) continue;
            if (bytes <= 0) { progress_refused = true; break; }
            remaining -= bytes; data += bytes; written += bytes;
        }
        pending->clear(); fsync(progress_fd); return;
    }
    // Before the normal mount, dump only once failure is already fatal.
    if (dumped || (severity != android::base::FATAL &&
                   std::string(message).find("InitFatalReboot: signal ") != 0)) return;
    dumped = true;
    struct statfs info {};
    bool own_mount = false;
    const char* path = "/metadata/lineage17-init-trace-09.log";
    constexpr const char* target = "/dev/lineage-init-fatal-trace-09";
    if (statfs("/metadata", &info) != 0 || info.f_type != 0xef53) {
        if (mkdir(target, 0700) != 0 && errno != EEXIST) return;
        if (mount("/dev/block/by-name/metadata", target, "ext4",
                  MS_NODEV | MS_NOSUID | MS_NOEXEC | MS_NOATIME, nullptr) != 0) return;
        own_mount = true;
        path = "/dev/lineage-init-fatal-trace-09/lineage17-init-trace-09.log";
    }
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd >= 0) {
        const char* data = pending->data();
        size_t remaining = pending->size();
        while (remaining) {
            ssize_t bytes = write(fd, data, remaining);
            if (bytes < 0 && errno == EINTR) continue;
            if (bytes <= 0) break;
            remaining -= bytes;
            data += bytes;
        }
        fsync(fd);
        close(fd);
    }
    // Always close the output before unmounting an error-only private mount.
    if (own_mount) umount(target);
}
} }
'''

STAGE2_HEADER = r'''
#include <atomic>
#include <poll.h>
#include <signal.h>
#include <time.h>
namespace android { namespace init {
#if defined(FIRST_STAGE_INIT)
inline bool LineageCopyStage2ToRam(bool normal_boot) {
    if (!normal_boot) return true;
    int source = open("/lineage-stage2-init", O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
    if (source < 0) return false;
    struct stat info {};
    if (fstat(source, &info) != 0 || !S_ISREG(info.st_mode) || info.st_uid != 0 ||
        info.st_size < 4096 || info.st_size > 8*1024*1024) { close(source); return false; }
    int target = open("/dev/lineage-stage2-init", O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC, 0750);
    if (target < 0) { close(source); return false; }
    char buffer[16384]; size_t copied = 0; bool good = true;
    while (copied < static_cast<size_t>(info.st_size)) {
        ssize_t got = read(source, buffer, std::min(sizeof(buffer), static_cast<size_t>(info.st_size)-copied));
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) { good = false; break; }
        size_t offset = 0;
        while (offset < static_cast<size_t>(got)) {
            ssize_t done = write(target, buffer+offset, got-offset);
            if (done < 0 && errno == EINTR) continue;
            if (done <= 0) { good = false; break; }
            offset += done;
        }
        if (!good) break;
        copied += got;
    }
    close(target); close(source);
    return good && copied == static_cast<size_t>(info.st_size);
}
inline bool LineageBindStage2FromRam(bool normal_boot) {
    if (!normal_boot) return true;
    if (mount("/dev/lineage-stage2-init", "/system/bin/init", nullptr, MS_BIND, nullptr) != 0) return false;
    return mount(nullptr, "/system/bin/init", nullptr, MS_BIND|MS_REMOUNT|MS_NODEV, nullptr) == 0;
}
inline void LineageCaptureLoaderStderr(bool normal_boot) {
    if (!normal_boot) return;
    int fd = open("/metadata/lineage17-stage2-loader-09.log",
                  O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC|O_SYNC, 0600);
    if (fd < 0) return;
    dup2(fd, STDOUT_FILENO); dup2(fd, STDERR_FILENO); fsync(fd); close(fd);
}
#else
inline void LineageCaptureWrite(int fd, const char* data, size_t count, size_t& written) {
    constexpr size_t cap = 2*1024*1024;
    if (written >= cap) return;
    count = std::min(count, cap-written);
    while (count) {
        ssize_t done = write(fd, data, count);
        if (done < 0 && errno == EINTR) continue;
        if (done <= 0) break;
        written += done; count -= done; data += done;
    }
    fsync(fd);
}
inline void LineageCaptureSnapshot(int fd, size_t& written) {
    const char* paths[] = {"/proc/sys/kernel/random/boot_id", "/proc/1/wchan",
                          "/proc/1/status", "/proc/1/syscall", "/proc/1/mountinfo"};
    for (const char* path : paths) {
        LineageCaptureWrite(fd, "\n# SNAPSHOT ", 12, written);
        LineageCaptureWrite(fd, path, __builtin_strlen(path), written);
        LineageCaptureWrite(fd, "\n", 1, written);
        int source = open(path, O_RDONLY|O_CLOEXEC);
        if (source < 0) { LineageCaptureWrite(fd, "unavailable\n", 12, written); continue; }
        char buffer[4096]; size_t total = 0;
        while (total < 16384) {
            ssize_t got = read(source, buffer, std::min(sizeof(buffer), 16384-total));
            if (got < 0 && errno == EINTR) continue;
            if (got <= 0) break;
            total += got; LineageCaptureWrite(fd, buffer, got, written);
        }
        close(source);
    }
}
inline int LineageStartKernelCapture(bool normal_boot) {
    if (!normal_boot) return 0;
    int input = open("/dev/kmsg", O_RDONLY|O_NONBLOCK|O_CLOEXEC);
    if (input < 0) return -errno;
    int output = open("/metadata/lineage17-kmsg-trace-09.log",
                      O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC, 0600);
    if (output < 0) { int error=errno; close(input); return -error; }
    pid_t child = fork();
    if (child != 0) {
        int error=errno; close(output); close(input);
        return child < 0 ? -error : static_cast<int>(child);
    }
    // Child only: a hard timeout also bounds a potentially blocked proc read.
    signal(SIGALRM, SIG_DFL);
    sigset_t signals; sigemptyset(&signals); sigaddset(&signals, SIGALRM);
    sigprocmask(SIG_UNBLOCK, &signals, nullptr); alarm(130);
    lseek(input, 0, SEEK_SET);
    timespec started {}; clock_gettime(CLOCK_MONOTONIC, &started);
    size_t written=0; long next_snapshot=15;
    char buffer[16384];
    while (written < 2*1024*1024) {
        timespec now {}; clock_gettime(CLOCK_MONOTONIC, &now);
        long elapsed=now.tv_sec-started.tv_sec;
        if (elapsed >= 120) break;
        if (elapsed >= next_snapshot) {
            LineageCaptureSnapshot(output, written); next_snapshot += 30;
        }
        if (written >= 1536*1024) { poll(nullptr, 0, 250); continue; }
        pollfd item {input, POLLIN, 0};
        int ready=poll(&item, 1, 250);
        if (ready <= 0) continue;
        ssize_t got=read(input, buffer, sizeof(buffer));
        if (got > 0) LineageCaptureWrite(output, buffer, got, written);
    }
    fsync(output); close(output); close(input); _exit(0);
}
inline void LineageSecondStageTrace(android::base::LogId id,
        android::base::LogSeverity severity, const char* tag, const char* file,
        unsigned int line, const char* message) {
    struct RestoreErrno { int value; ~RestoreErrno() { errno = value; } } restore { errno };
    android::base::KernelLogger(id, severity, tag, file, line, message);
    static std::atomic_flag busy = ATOMIC_FLAG_INIT;
    if (busy.test_and_set()) return;
    struct Release { std::atomic_flag& flag; ~Release() { flag.clear(); } } release { busy };
    static int fd = -1;
    static bool refused = false;
    if (refused) return;
    if (fd < 0) {
        // Init has ordinary metadata-file write permission, not append.
        fd = open("/metadata/lineage17-stage2-trace-09.log",
                  O_WRONLY|O_CREAT|O_NOFOLLOW|O_CLOEXEC, 0600);
        if (fd < 0) { refused = true; return; }
    }
    struct stat info {};
    if (fstat(fd, &info) != 0 || !S_ISREG(info.st_mode) || info.st_uid != 0 ||
        (info.st_mode & 0777) != 0600 || info.st_nlink != 1 || info.st_size >= 2*1024*1024) {
        refused = true; close(fd); fd = -1; return;
    }
    off_t end = lseek(fd, 0, SEEK_END);
    if (end < 0 || end >= 2*1024*1024) { refused = true; close(fd); fd = -1; return; }
    std::string entry = std::string(tag ? tag : "init") + ": " + message + "\n";
    size_t remaining = std::min(entry.size(), static_cast<size_t>(2*1024*1024-end));
    const char* data = entry.data();
    while (remaining) {
        ssize_t done = write(fd, data, remaining);
        if (done < 0 && errno == EINTR) continue;
        if (done <= 0) { refused = true; break; }
        remaining -= done; data += done;
    }
    fsync(fd);
}
#endif
} }
'''

def sha(data):
    return hashlib.sha256(data).hexdigest()


def reconstruct(files):
    """Require exact pinned source before making the diagnostic-only additions."""
    if set(files) != set(PREIMAGES):
        raise ValueError('exact first-stage diagnostic source set required')
    for name, expected in PREIMAGES.items():
        if sha(files[name]) != expected:
            raise ValueError('first-stage diagnostic preimage mismatch: ' + name)
    result = dict(files)
    # The only mount-source addition logs AFTER its existing mount succeeds.
    name = 'system/core/init/first_stage_mount.cpp'
    before = b'    bool mounted = (fs_mgr_do_mount_one(*begin) == 0);\n'
    marker = b'    if (mounted && begin->mount_point == "/metadata") LOG(INFO) << "LINEAGE_INIT_TRACE normal final metadata mounted";\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, before + marker)
    assert result[name].replace(marker, b'') == files[name]
    name = 'system/core/init/first_stage_init.cpp'
    before = b'    execv(path, const_cast<char**>(args));\n'
    marker = b'    if (lineage_normal_boot) LOG(INFO) << "LINEAGE_INIT_TRACE first-stage exec selinux_setup";\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, marker + before)
    assert result[name].replace(marker, b'') == files[name]
    before = b'#include "first_stage_init.h"\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, before + b'#include "lineage_init_trace.h"\n')
    before = b'    InitKernelLogging(argv);\n'
    addition = b'    const bool lineage_normal_boot = !IsRecoveryMode();\n    if (!LineageCopyStage2ToRam(lineage_normal_boot)) PLOG(FATAL) << "LINEAGE_INIT_TRACE RAM init copy failed";\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, before + addition)
    before = b'    struct stat new_root_info{};\n'
    addition = b'    if (!LineageBindStage2FromRam(lineage_normal_boot)) PLOG(FATAL) << "LINEAGE_INIT_TRACE RAM init bind flags failed";\n    if (lineage_normal_boot) LOG(INFO) << "LINEAGE_INIT_TRACE diagnostic second-stage init bound from RAM";\n\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, addition + before)
    before = b'    execv(path, const_cast<char**>(args));\n'
    addition = b'    LineageCaptureLoaderStderr(lineage_normal_boot);\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, addition + before)
    name = 'system/core/init/init.cpp'
    before = b'#include "init.h"\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, before + b'#include "lineage_init_trace.h"\n')
    before = b'    LOG(INFO) << "init second stage started!";\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, b'    selinux_android_restorecon("/metadata/lineage17-stage2-trace-09.log", 0);\n' + before)
    result[name] = result[name].replace(before, before + b'    selinux_android_restorecon("/dev/kmsg", 0);\n    int lineage_capture_pid = LineageStartKernelCapture(!IsRecoveryMode());\n    LOG(INFO) << "LINEAGE_STAGE2_TRACE kernel capture pid or error " << lineage_capture_pid;\n')
    for call in (b'    PropertyInit();\n', b'    MountExtraFilesystems();\n', b'    SelinuxRestoreContext();\n', b'    StartPropertyService(&property_fd);\n', b'    InitializeSubcontext();\n', b'    LoadBootScripts(am, sm);\n'):
        assert result[name].count(call) == 1
        label=call.strip().decode().replace('"','')
        result[name] = result[name].replace(call, ('    LOG(INFO) << "LINEAGE_STAGE2_TRACE before '+label+'";\n').encode() + call + ('    LOG(INFO) << "LINEAGE_STAGE2_TRACE after '+label+'";\n').encode())
    name = 'system/core/init/selinux.cpp'
    before = b'#include "selinux.h"\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, before + b'#include "lineage_init_trace.h"\n')
    before = b'        android::base::KernelLogger(android::base::MAIN, severity, "selinux", nullptr, 0, buf);\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, b'        LineageSecondStageTrace(android::base::MAIN, severity, "selinux", nullptr, 0, buf);\n')
    before = b'    InitKernelLogging(argv);\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, before + b'    LOG(INFO) << "LINEAGE_STAGE2_TRACE selinux_setup entry";\n')
    before = b'        LoadSelinuxPolicyAndroid();\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, b'        LOG(INFO) << "LINEAGE_STAGE2_TRACE before Android policy load";\n' + before + b'        LOG(INFO) << "LINEAGE_STAGE2_TRACE after Android policy load";\n')
    before = b'    execv(path, const_cast<char**>(args));\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, b'    LOG(INFO) << "LINEAGE_STAGE2_TRACE exec second_stage";\n' + before)
    name = 'system/core/init/util.cpp'
    before = b'#include "util.h"\n'
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, before + b'#include "lineage_init_trace.h"\n')
    before = b'''void InitKernelLogging(char** argv) {
    SetFatalRebootTarget();
    android::base::InitLogging(argv, &android::base::KernelLogger, InitAborter);
}'''
    after = b'''void InitKernelLogging(char** argv) {
    SetFatalRebootTarget();
    if (IsRecoveryMode()) {
        android::base::InitLogging(argv, &android::base::KernelLogger, InitAborter);
        return;
    }
#if defined(FIRST_STAGE_INIT)
    android::base::InitLogging(argv, &LineageFirstStageTrace, InitAborter);
#else
    android::base::InitLogging(argv, &LineageSecondStageTrace, InitAborter);
#endif
}'''
    assert result[name].count(before) == 1
    result[name] = result[name].replace(before, after)
    result['system/core/init/lineage_init_trace.h'] = (HEADER + STAGE2_HEADER).encode()
    return result


def validate_run(inputs, relative, digest):
    if inputs.get('target') != 'init-diagnostic':
        raise ValueError('diagnostic is prohibited for release build targets')
    if inputs.get('source_hashes', {}).get(relative) != digest:
        raise ValueError('diagnostic helper differs from frozen run inputs')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-tree', type=Path, required=True)
    p.add_argument('--candidate-inputs', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    isolated(args.source_tree)
    inputs = json.loads(args.candidate_inputs.read_text())
    repo = Path(__file__).resolve().parents[2]
    relative = str(Path(__file__).relative_to(repo))
    validate_run(inputs, relative, sha(Path(__file__).read_bytes()))
    originals = {n: safe_file(args.source_tree, n).read_bytes() for n in PREIMAGES}
    changed = reconstruct(originals)
    if safe_file(args.source_tree, 'system/core/init/lineage_init_trace.h').exists():
        raise ValueError('diagnostic header already exists')
    for name, data in changed.items():
        safe_file(args.source_tree, name).write_bytes(data)
    args.report.write_text(json.dumps({
        'diagnostic_only': True, 'target': inputs['target'],
        'normal_mount_order_unchanged': True,
        'preimages': PREIMAGES, 'postimages': {n: sha(d) for n, d in changed.items()},
        'ram_only_second_stage': True,
        'protocol': '09',
        'recovery_passthrough': True,
        'ram_bind_clears_nosuid': True,
        'loader_stderr_capture': True,
        'bounded_kernel_and_init_snapshots': True,
        'scope': 'Diagnostic init pair. Normal partition mount order/checks and SELinux load/enforcement remain. First stage copies the paired ramdisk stage2 ELF to dev tmpfs and bind mounts it over system/bin/init after normal OS mounts; underlying system image unchanged. Bounded first-stage, stage2 and kernel logs with PID1 snapshots. No format, credential access, raw writer, firmware, global policy change or OTA.'}, indent=2))


if __name__ == '__main__':
    main()
