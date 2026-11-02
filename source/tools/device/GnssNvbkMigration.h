#pragma once
#include "GnssNvbkPatch.h"

namespace realme_gnss {
enum class MigrationResult {
  kNotApplicable = 0, kAlreadyEnabled = 1, kApplied = 2,
  kRefused = 3, kJournalFailed = 4, kPreimageChanged = 5,
  kWriteFailed = 6, kVerifyFailed = 7, kSourceChanged = 8,
};

// Implementations bind slot numbers to the two static NVBK devices only. They
// must enforce geometry/device identity, a durable private undo journal and exact
// I/O. The journal supplements required off-device backups; it is not a full copy.
// No implementation may change read-only protection or substitute another node.
class MigrationIO {
 public:
  virtual ~MigrationIO() = default;
  virtual bool Read(int slot, std::vector<uint8_t>* image) = 0;
  virtual bool Journal(int slot, const std::vector<uint8_t>& original) = 0;
  virtual bool Write(int slot, size_t offset, const uint8_t* data, size_t bytes) = 0;
  virtual bool Sync(int slot) = 0;
};

// Production callers bind read-only model/project and distinct source/target
// slots, and pass ReviewedProfile(). A changed inactive target must never be
// activated after a failure. There is no automatic source/EFS restoration.
MigrationResult Migrate(const std::string& model, const std::string& project,
                        int source_slot, int target_slot, const Profile& profile,
                        Sha256 sha256, MigrationIO* io, std::string* error);
}  // namespace realme_gnss
