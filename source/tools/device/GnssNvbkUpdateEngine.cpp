#include "GnssNvbkUpdateEngine.h"
#ifdef __ANDROID__
#include "GnssNvbkPosix.h"
#include <android-base/properties.h>
#include <base/logging.h>
#include <cstring>
#include "update_engine/common/hash_calculator.h"

namespace chromeos_update_engine {
namespace {
bool Hash(const uint8_t* data, size_t bytes, uint8_t* output) {
  brillo::Blob hash;
  if (!HashCalculator::RawHashOfBytes(data, bytes, &hash) || hash.size() != 32)
    return false;
  std::memcpy(output, hash.data(), hash.size());
  return true;
}
}  // namespace

bool MigrateRealmeGnssNvbk(BootControlInterface* boot_control,
                          const InstallPlan& install_plan, std::string* error) {
  const std::string model = android::base::GetProperty("ro.product.model", "");
  if (model != "RMX3301") return true;
  const std::string project = android::base::GetProperty("ro.boot.prjname", "");
  if (!boot_control || project != "21631") {
    if (error) *error = "Realme GNSS migration requires verified project21631";
    return false;
  }
  const auto current = boot_control->GetCurrentSlot();
  if ((current != 0 && current != 1) ||
      (install_plan.target_slot != 0 && install_plan.target_slot != 1) ||
      (install_plan.source_slot != BootControlInterface::kInvalidSlot &&
       install_plan.source_slot != current)) {
    if (error) *error = "Realme GNSS migration source/target slot mismatch";
    return false;
  }
  std::array<std::string, 2> paths;
  for (unsigned slot = 0; slot < paths.size(); ++slot) {
    bool dynamic = false;
    if (!boot_control->GetPartitionDevice("oplusstanvbk", slot,
            true /* not_in_payload */, &paths[slot], &dynamic) || dynamic) {
      if (error) *error = "Realme GNSS static partition identity unavailable";
      return false;
    }
  }
  auto io = realme_gnss::CreatePosixMigrationIO(&Hash, paths);
  const auto result = realme_gnss::Migrate(model, project, current,
      install_plan.target_slot, realme_gnss::ReviewedProfile(), &Hash, io.get(), error);
  using Result = realme_gnss::MigrationResult;
  if (result == Result::kApplied) {
    LOG(INFO) << "Realme GNSS NVBK migration applied to inactive slot";
    return true;
  }
  if (result == Result::kAlreadyEnabled) {
    LOG(INFO) << "Realme GNSS NVBK migration already enabled in inactive slot";
    return true;
  }
  return result == Result::kNotApplicable;
}
}  // namespace chromeos_update_engine
#endif
