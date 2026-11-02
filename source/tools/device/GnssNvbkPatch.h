// Offline/native transformation core. No device/file I/O or installer privileges.
// NVBK format/field: Rapper_skull's libnvbk9801184c and L5 modulebdec3a14,
// Apache-2.0. Full source pins/credit are in tools/gnss_nvbk.py.
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace realme_gnss {
using Digest = std::array<uint8_t, 32>;
using Sha256 = bool (*)(const uint8_t*, size_t, uint8_t*);
struct Profile {
  size_t image_bytes;
  Digest canonical_gnss;
};
struct Patch {
  std::vector<uint8_t> image;
  size_t field_offset = 0;
  size_t checksum_offset = 0;
  bool changed = false;
};
Profile ReviewedProfile();
// Caller supplies actual SHA256, not a permissive checksum substitute. The
// production installer must use ReviewedProfile, bind its device/slot/preimage
// and perform separate durable backup/write/readback/error handling.
bool Prepare(const std::vector<uint8_t>& input, const Profile& profile,
             bool enable, Sha256 sha256, Patch* output, std::string* error);
}  // namespace realme_gnss
