#include "GnssNvbkMigration.h"

namespace realme_gnss {
namespace {
MigrationResult Failure(MigrationResult result, std::string* error,
                        const char* message) {
  if (error) *error = message;
  return result;
}
}  // namespace

MigrationResult Migrate(const std::string& model, const std::string& project,
                        int source_slot, int target_slot, const Profile& profile,
                        Sha256 sha256, MigrationIO* io, std::string* error) {
  if (model != "RMX3301") return MigrationResult::kNotApplicable;
  if (project != "21631" || !io || !sha256 || source_slot < 0 || source_slot > 1 ||
      target_slot < 0 || target_slot > 1 || source_slot == target_slot)
    return Failure(MigrationResult::kRefused, error, "unsupported device/slot contract");
  std::vector<uint8_t> original;
  if (!io->Read(target_slot, &original))
    return Failure(MigrationResult::kRefused, error, "target read failed");
  Patch patch;
  if (!Prepare(original, profile, true, sha256, &patch, error))
    return MigrationResult::kRefused;
  if (!patch.changed) {
    // A previous failed update may have left correct but unsynced cache data.
    // Idempotence avoids data writes, while still requiring durable state.
    if (!io->Sync(target_slot))
      return Failure(MigrationResult::kWriteFailed, error, "existing target sync failed");
    return MigrationResult::kAlreadyEnabled;
  }

  std::vector<uint8_t> source;
  Patch source_check;
  if (!io->Read(source_slot, &source) ||
      !Prepare(source, profile, true, sha256, &source_check, error))
    return Failure(MigrationResult::kRefused, error, "source NVBK contract unavailable");
  // A durable undo journal precedes both writes. Re-read the target afterward so a
  // stale preparation never overwrites a concurrently changed configuration.
  if (!io->Journal(target_slot, original))
    return Failure(MigrationResult::kJournalFailed, error, "durable undo journal failed");
  std::vector<uint8_t> current;
  if (!io->Read(target_slot, &current) || current != original)
    return Failure(MigrationResult::kPreimageChanged, error, "target preimage changed");
  if (!io->Write(target_slot, patch.field_offset,
                 patch.image.data() + patch.field_offset, 5) ||
      !io->Write(target_slot, patch.checksum_offset,
                 patch.image.data() + patch.checksum_offset, 32) ||
      !io->Sync(target_slot))
    return Failure(MigrationResult::kWriteFailed, error,
                   "target write/sync failed; stop activation, preserve backup");
  if (!io->Read(target_slot, &current) || current != patch.image)
    return Failure(MigrationResult::kVerifyFailed, error, "target readback mismatch");
  if (!io->Read(source_slot, &current) || current != source)
    return Failure(MigrationResult::kSourceChanged, error, "source changed during migration");
  if (error) error->clear();
  return MigrationResult::kApplied;
}
}  // namespace realme_gnss
