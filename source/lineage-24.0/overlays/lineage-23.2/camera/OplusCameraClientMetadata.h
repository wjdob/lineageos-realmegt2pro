/* Device compatibility for the Oplus HIDL camera session contract. */
#ifndef ANDROID_CAMERA_OPLUS_CLIENT_METADATA_H
#define ANDROID_CAMERA_OPLUS_CLIENT_METADATA_H

#include <camera/CameraMetadata.h>
#include <camera/VendorTagDescriptor.h>
#include <string>
#include <utils/String8.h>

namespace android {
namespace camera3 {

// The caller is captured from CameraService's checked client, never from a request tag.
// The SDK cannot supply this key through the normal session-key filter on this HAL.
inline status_t updateOplusClientMetadata(metadata_vendor_id_t vendorId,
        const std::string& verifiedPackageName, CameraMetadata& sessionParams) {
    if (verifiedPackageName.empty()) return OK;

    sp<VendorTagDescriptorCache> cache = VendorTagDescriptorCache::getGlobalVendorTagCache();
    sp<VendorTagDescriptor> descriptor;
    if (cache == nullptr ||
            cache->getVendorTagDescriptor(vendorId, &descriptor) != OK || descriptor == nullptr) {
        return OK;
    }
    uint32_t tag;
    if (CameraMetadata::getTagFromName("com.oplus.packageName", descriptor.get(), &tag) != OK) {
        return OK;
    }
    // Match the stock String8 overload, including its terminating zero byte. Propagate
    // update/type errors; never report a configured session or invent HAL buffer counts.
    return sessionParams.update(tag, String8(verifiedPackageName.c_str()));
}

} // namespace camera3
} // namespace android

#endif
