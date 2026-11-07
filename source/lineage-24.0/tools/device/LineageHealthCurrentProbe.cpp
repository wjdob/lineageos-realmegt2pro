/* Engineering-only read probe compiled with the exact reconstructed QTI main.cpp.
 * Renames its entry point and calls only config initialization and local getters.
 * Never starts HalHealthLoop/charger mode, registers a service or changes policy.
 */
#ifndef HEALTH_CURRENT_CANDIDATE_SOURCE
#error "Compile with the exact reviewed candidate main.cpp path"
#endif
#define main CandidateHealthServiceUnusedMain
#include HEALTH_CURRENT_CANDIDATE_SOURCE
#undef main
#include <cstdio>

int main() {
    if (android::base::GetProperty("ro.boot.prjname", "") != "21631") return 20;
    auto config = std::make_unique<healthd_config>();
    ::android::hardware::health::InitHealthdConfig(config.get());
    qti_healthd_board_init(config.get());
    auto service = ndk::SharedRefBase::make<Rmx3301Health>("diagnostic-unregistered", std::move(config));
    int32_t before = 0, corrected = 0, after = 0;
    aidl::android::hardware::health::HealthInfo info;
    if (!service->Health::getCurrentNowMicroamps(&before).isOk() ||
        !service->getCurrentNowMicroamps(&corrected).isOk() ||
        !service->getHealthInfo(&info).isOk() ||
        !service->Health::getCurrentNowMicroamps(&after).isOk()) return 21;
    std::printf("{\"raw_before_milliamps\":%d,\"corrected_direct_microamps\":%d,"
                "\"corrected_health_info_microamps\":%d,\"raw_after_milliamps\":%d,"
                "\"capacity_percent\":%d,\"charge_counter_microah\":%d,"
                "\"status\":%d,\"registered_service\":false}\n",
                before, corrected, info.batteryCurrentMicroamps, after,
                info.batteryLevel, info.batteryChargeCounterUah, static_cast<int>(info.batteryStatus));
    return 0;
}
