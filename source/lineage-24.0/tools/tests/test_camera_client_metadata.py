"""Exercise the actual native caller-metadata helper with controlled metadata providers."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

STUB = r'''
#pragma once
#include <cstdint>
#include <map>
#include <memory>
#include <string>
namespace android {
using status_t = int;
using metadata_vendor_id_t = uint64_t;
constexpr status_t OK = 0;
template<class T> using sp = std::shared_ptr<T>;
struct String8 { std::string value; explicit String8(const char* s): value(s) {} };
struct VendorTagDescriptor { uint32_t tag = 123; int tagStatus = OK; };
struct VendorTagDescriptorCache {
    inline static sp<VendorTagDescriptorCache> global;
    std::map<uint64_t, sp<VendorTagDescriptor>> providers;
    uint64_t queriedId = 0;
    static sp<VendorTagDescriptorCache> getGlobalVendorTagCache() { return global; }
    int getVendorTagDescriptor(uint64_t id, sp<VendorTagDescriptor>* out) {
        queriedId = id;
        if (!providers.count(id)) return -2;
        *out = providers[id]; return OK;
    }
};
struct CameraMetadata {
    std::map<uint32_t, std::string> values;
    int updateStatus = OK;
    int updates = 0;
    static int getTagFromName(const char* name, const VendorTagDescriptor* d, uint32_t* tag) {
        if (std::string(name) != "com.oplus.packageName") return -2;
        if (d->tagStatus != OK) return d->tagStatus;
        *tag = d->tag; return OK;
    }
    int update(uint32_t tag, const String8& value) {
        ++updates;
        if (updateStatus != OK) return updateStatus;
        values[tag] = value.value + '\0'; return OK;
    }
};
}
'''

FIXTURE = r'''
#include "OplusCameraClientMetadata.h"
#include <cassert>
#include <iostream>
using namespace android;
using android::camera3::updateOplusClientMetadata;
int main() {
    int cases = 0;
    auto cache = std::make_shared<VendorTagDescriptorCache>();
    auto descriptor = std::make_shared<VendorTagDescriptor>();
    cache->providers[42] = descriptor;
    VendorTagDescriptorCache::global = cache;
    const std::string realName = "com.oplus.camera";
    {
        CameraMetadata p;
        assert(updateOplusClientMetadata(42, realName, p) == OK);
        assert(p.values.at(123) == realName + '\0');
        assert(cache->queriedId == 42); ++cases;
    }
    {
        CameraMetadata p; p.values[123] = "forged.name";
        assert(updateOplusClientMetadata(42, "ordinary.camera.app", p) == OK);
        assert(p.values.at(123) == std::string("ordinary.camera.app") + '\0'); ++cases;
    }
    {
        CameraMetadata p; p.values[7] = "preserve";
        assert(updateOplusClientMetadata(42, "", p) == OK);
        assert(p.values.size() == 1 && p.values.at(7) == "preserve" && p.updates == 0); ++cases;
    }
    {
        CameraMetadata p; VendorTagDescriptorCache::global.reset();
        assert(updateOplusClientMetadata(42, realName, p) == OK && p.updates == 0);
        VendorTagDescriptorCache::global = cache; ++cases;
    }
    {
        CameraMetadata p;
        assert(updateOplusClientMetadata(999, realName, p) == OK && p.updates == 0); ++cases;
    }
    {
        CameraMetadata p; cache->providers[41] = nullptr;
        assert(updateOplusClientMetadata(41, realName, p) == OK && p.updates == 0); ++cases;
    }
    {
        CameraMetadata p; descriptor->tagStatus = -2;
        assert(updateOplusClientMetadata(42, realName, p) == OK && p.updates == 0);
        descriptor->tagStatus = OK; ++cases;
    }
    {
        CameraMetadata p; p.updateStatus = -22; p.values[7] = "preserve";
        assert(updateOplusClientMetadata(42, realName, p) == -22);
        assert(p.values.size() == 1 && p.values.at(7) == "preserve"); ++cases;
    }
    {
        CameraMetadata p; auto other = std::make_shared<VendorTagDescriptor>(); other->tag = 456;
        cache->providers[43] = other;
        assert(updateOplusClientMetadata(43, realName, p) == OK);
        assert(p.values.count(123) == 0 && p.values.at(456) == realName + '\0'); ++cases;
    }
    assert(cases == 9);
    std::cout << "9 native helper cases passed\n";
}
'''


class CameraClientMetadataTests(unittest.TestCase):
    def test_verified_caller_and_provider_boundaries(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('Host C++ compiler unavailable; native helper check blocked')
        scratch = ROOT/'tmp/test-camera-client-metadata'
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            work = Path(directory)
            (work/'camera').mkdir()
            (work/'utils').mkdir()
            (work/'camera/CameraMetadata.h').write_text(STUB)
            (work/'camera/VendorTagDescriptor.h').write_text('#include "CameraMetadata.h"\n')
            (work/'utils/String8.h').write_text('#include <camera/CameraMetadata.h>\n')
            (work/'fixture.cpp').write_text(FIXTURE)
            result = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                     '-I'+str(work), '-I'+str(ROOT/'overlays/lineage-23.2/camera'),
                                     str(work/'fixture.cpp'), '-o', str(work/'fixture')],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(work/'fixture')], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '9 native helper cases passed')
