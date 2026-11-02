#pragma once
#ifdef __ANDROID__
#include <string>
#include "update_engine/common/boot_control_interface.h"
#include "update_engine/payload_consumer/install_plan.h"

namespace chromeos_update_engine {
bool MigrateRealmeGnssNvbk(BootControlInterface* boot_control,
                          const InstallPlan& install_plan, std::string* error);
}  // namespace chromeos_update_engine
#endif
