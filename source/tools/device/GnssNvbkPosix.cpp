#include "GnssNvbkPosix.h"
#include <algorithm>
#include <cerrno>
#include <climits>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <linux/fs.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace realme_gnss {
namespace {
constexpr const char* kNames[2] = {"oplusstanvbk_a", "oplusstanvbk_b"};
constexpr const char* kJournalDirectory = "/metadata/ota";

class Fd {
 public:
  explicit Fd(int fd = -1) : value(fd) {}
  ~Fd() { if (value >= 0) close(value); }
  Fd(const Fd&) = delete;
  Fd& operator=(const Fd&) = delete;
  int value;
};

bool ReadAt(int fd, uint8_t* data, size_t size) {
  size_t done = 0;
  while (done < size) {
    const ssize_t count = pread(fd, data + done, size - done, done);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) return false;
    done += static_cast<size_t>(count);
  }
  return true;
}

std::string Hex(const Digest& bytes) {
  std::string result;
  for (const uint8_t b : bytes) {
    result.push_back("0123456789abcdef"[b >> 4]);
    result.push_back("0123456789abcdef"[b & 15]);
  }
  return result;
}

bool IsJournalDirectory(const struct stat& st, uid_t owner) {
  const auto mode = st.st_mode & 0777;
  return S_ISDIR(st.st_mode) && st.st_uid == owner &&
         (mode == 0700 || mode == 0750);
}

bool ValidPaths(const std::array<std::string, 2>& paths) {
  for (int slot = 0; slot < 2; ++slot) {
    if (paths[slot] != std::string("/dev/block/by-name/") + kNames[slot] &&
        paths[slot] != std::string("/dev/block/bootdevice/by-name/") + kNames[slot])
      return false;
  }
  return true;
}

bool StoreJournalAt(const char* directory_path, uid_t owner,
                    const std::string& name, const std::vector<uint8_t>& journal) {
  if (name.empty() || name == "." || name == ".." ||
      !std::all_of(name.begin(), name.end(), [](char c) {
        return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
               (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-';
      })) return false;
  // Use the existing OTA metadata directory: no new directory, permissions or
  // SELinux rule are needed. The undo file itself remains root-only0600.
  struct stat before;
  if (lstat(directory_path, &before) || !IsJournalDirectory(before, owner)) return false;
  Fd directory(open(directory_path, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW));
  if (directory.value < 0) return false;
  struct stat opened;
  if (fstat(directory.value, &opened) || !IsJournalDirectory(opened, owner) ||
      before.st_dev != opened.st_dev || before.st_ino != opened.st_ino) return false;
  Fd file(openat(directory.value, name.c_str(), O_RDWR | O_CREAT | O_EXCL |
                 O_CLOEXEC | O_NOFOLLOW, 0600));
  const bool created = file.value >= 0;
  if (!created) {
    if (errno != EEXIST) return false;
    file.value = openat(directory.value, name.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (file.value < 0) return false;
  }
  struct stat st;
  if (fstat(file.value, &st) || !S_ISREG(st.st_mode) || st.st_uid != owner ||
      (st.st_mode & 0777) != 0600 || st.st_nlink != 1) return false;
  if (created) {
    ssize_t count;
    do { count = write(file.value, journal.data(), journal.size()); }
    while (count < 0 && errno == EINTR);
    if (count != static_cast<ssize_t>(journal.size()) || fsync(file.value)) return false;
  }
  if (fstat(file.value, &st) || st.st_size != static_cast<off_t>(journal.size())) return false;
  std::vector<uint8_t> verified(journal.size());
  if (!ReadAt(file.value, verified.data(), verified.size()) || verified != journal) return false;
  // Also sync a verified existing journal, which may originate from a prior
  // interrupted update. Never truncate/delete an unexpected or partial record.
  return fsync(file.value) == 0 && fsync(directory.value) == 0;
}

class PosixIO final : public MigrationIO {
 public:
  PosixIO(Sha256 hash, const std::array<std::string, 2>& paths) : hash_(hash), paths_(paths) {}
  ~PosixIO() override {
    for (int fd : descriptors_) if (fd >= 0) close(fd);
    if (writer_ >= 0) close(writer_);
  }
  bool Read(int slot, std::vector<uint8_t>* image) override {
    if (!image || !OpenSlot(slot)) return false;
    image->resize(ReviewedProfile().image_bytes);
    return ReadAt(descriptors_[slot], image->data(), image->size());
  }
  bool Journal(int slot, const std::vector<uint8_t>& original) override {
    if (geteuid() != 0 || armed_slot_ != -1 || !OpenSlot(slot) || !hash_) return false;
    Patch patch;
    std::string error;
    if (!Prepare(original, ReviewedProfile(), true, hash_, &patch, &error) || !patch.changed)
      return false;
    Digest before, after;
    if (!hash_(original.data(), original.size(), before.data()) ||
        !hash_(patch.image.data(), patch.image.size(), after.data())) return false;
    // Versioned, little-endian undo record: magic, slot, range offsets, original
    // five field bytes /32 checksum bytes, full image hashes, record SHA256.
    std::vector<uint8_t> journal = {'R','G','N','S','S','0','1',0,static_cast<uint8_t>(slot)};
    for (size_t offset : {patch.field_offset, patch.checksum_offset})
      for (unsigned i = 0; i < 8; ++i) journal.push_back(static_cast<uint8_t>(uint64_t(offset) >> (8 * i)));
    journal.insert(journal.end(), original.begin() + patch.field_offset,
                   original.begin() + patch.field_offset + 5);
    journal.insert(journal.end(), original.begin() + patch.checksum_offset,
                   original.begin() + patch.checksum_offset + 32);
    journal.insert(journal.end(), before.begin(), before.end());
    journal.insert(journal.end(), after.begin(), after.end());
    Digest record;
    if (!hash_(journal.data(), journal.size(), record.data())) return false;
    journal.insert(journal.end(), record.begin(), record.end());
    const std::string name = std::string("realme-gnss-nvbk-v1-") + kNames[slot] + "-" + Hex(before) + ".journal";
    if (!StoreJournalAt(kJournalDirectory, 0, name, journal)) return false;
    original_ = original; expected_ = std::move(patch); armed_slot_ = slot;
    return true;
  }
  bool Write(int slot, size_t offset, const uint8_t* data, size_t bytes) override {
    if (failed_ || slot < 0 || slot > 1 || armed_slot_ < 0 ||
        slot != armed_slot_ || !data || writes_ >= 2) return false;
    const size_t expected_offset = writes_ == 0 ? expected_.field_offset : expected_.checksum_offset;
    const size_t expected_size = writes_ == 0 ? 5 : 32;
    if (offset != expected_offset || bytes != expected_size ||
        !std::equal(data, data + bytes, expected_.image.begin() + offset)) return false;
    if (writer_ < 0) {
      writer_ = OpenBoundDevice(slot, O_RDWR);
      std::vector<uint8_t> current(original_.size());
      if (writer_ < 0 || !ReadAt(writer_, current.data(), current.size()) || current != original_)
        return Failed();
    }
    ssize_t count;
    do { count = pwrite(writer_, data, bytes, static_cast<off_t>(offset)); }
    while (count < 0 && errno == EINTR);
    if (count != static_cast<ssize_t>(bytes)) return Failed();
    ++writes_;
    return true;
  }
  bool Sync(int slot) override {
    if (failed_ || !OpenSlot(slot)) return false;
    if (writer_ >= 0 && slot != armed_slot_) return false;
    return fsync(writer_ >= 0 ? writer_ : descriptors_[slot]) == 0;
  }

 private:
  bool Failed() { failed_ = true; return false; }
  bool OpenSlot(int slot) {
    if (slot < 0 || slot > 1 || geteuid() != 0) return false;
    if (descriptors_[slot] >= 0) return true;
    descriptors_[slot] = OpenBoundDevice(slot, O_RDONLY);
    return descriptors_[slot] >= 0;
  }
  int OpenBoundDevice(int slot, int access) {
    if (!ValidPaths(paths_)) return -1;
    const std::string& path = paths_[slot];
    char resolved[PATH_MAX];
    if (!realpath(path.c_str(), resolved)) return -1;
    const std::string canonical(resolved);
    constexpr const char* prefix = "/dev/block/";
    if (canonical.compare(0, std::strlen(prefix), prefix)) return -1;
    const std::string basename = canonical.substr(std::strlen(prefix));
    if (basename.empty() || !std::all_of(basename.begin(), basename.end(), [](char c) {
          return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
        })) return -1;
    Fd descriptor(open(canonical.c_str(), access | O_CLOEXEC | O_NOFOLLOW));
    struct stat st;
    uint64_t size = 0;
    if (descriptor.value < 0 || fstat(descriptor.value, &st) || !S_ISBLK(st.st_mode) ||
        st.st_uid != 0 || (st.st_mode & 0002) || ioctl(descriptor.value, BLKGETSIZE64, &size) ||
        size != ReviewedProfile().image_bytes) return -1;
    if (descriptors_[slot] >= 0) {
      struct stat old;
      if (fstat(descriptors_[slot], &old) || old.st_rdev != st.st_rdev) return -1;
    }
    const int other = 1 - slot;
    if (descriptors_[other] >= 0) {
      struct stat old;
      if (fstat(descriptors_[other], &old) || old.st_rdev == st.st_rdev) return -1;
    }
    const int result = descriptor.value; descriptor.value = -1; return result;
  }
  Sha256 hash_;
  std::array<std::string, 2> paths_;
  int descriptors_[2] = {-1,-1};
  int writer_ = -1, armed_slot_ = -1;
  unsigned writes_ = 0;
  bool failed_ = false;
  std::vector<uint8_t> original_;
  Patch expected_;
};
}  // namespace

std::unique_ptr<MigrationIO> CreatePosixMigrationIO(
    Sha256 sha256, const std::array<std::string, 2>& paths) {
  if (!sha256 || !ValidPaths(paths)) return nullptr;
  return std::unique_ptr<MigrationIO>(new PosixIO(sha256, paths));
}
#ifdef GNSS_NVBK_HOST_TEST
extern "C" bool store_gnss_journal_fixture(const char* directory,
    uint32_t owner, const char* name, const uint8_t* data, size_t bytes) {
  return StoreJournalAt(directory, owner, name, std::vector<uint8_t>(data, data + bytes));
}
extern "C" bool valid_gnss_paths_fixture(const char* a, const char* b) {
  return a && b && ValidPaths({std::string(a), std::string(b)});
}
#endif
}  // namespace realme_gnss
