#include "GnssNvbkPatch.h"
#include <algorithm>
#include <cstring>
#include <utility>

namespace realme_gnss {
namespace {
uint16_t Le16(const std::vector<uint8_t>& x, size_t p) {
  return uint16_t(x[p]) | (uint16_t(x[p + 1]) << 8);
}
uint32_t Le32(const std::vector<uint8_t>& x, size_t p) {
  return uint32_t(x[p]) | (uint32_t(x[p + 1]) << 8) |
         (uint32_t(x[p + 2]) << 16) | (uint32_t(x[p + 3]) << 24);
}
bool Fail(std::string* error, const char* message) {
  if (error) *error = message;
  return false;
}
}  // namespace

Profile ReviewedProfile() {
  return {20U * 1024U * 1024U,
          {0x8b,0x26,0xc8,0xc1,0x8b,0xfc,0xee,0x00,
           0x28,0xc8,0x02,0x08,0xaf,0xad,0x7a,0xcb,
           0x93,0x6e,0x11,0x5c,0xc5,0x3e,0xe6,0xbc,
           0xda,0x4a,0x04,0x83,0xf0,0x2b,0xe3,0x82}};
}

bool Prepare(const std::vector<uint8_t>& input, const Profile& profile,
             bool enable, Sha256 sha256, Patch* output, std::string* error) {
  if (!output || !sha256) return Fail(error, "missing output/hash implementation");
  if (input.size() != profile.image_bytes || input.size() < 512)
    return Fail(error, "unsupported image length");
  if (std::memcmp(input.data(), "OEMNVBK\0", 8) || Le16(input, 8) != 1 ||
      input[10] != 1 || input[11] != 1 || Le32(input, 13) != 28 || input[17] != 2)
    return Fail(error, "unsupported static NVBK header");
  const size_t count = input[12];
  if (!count) return Fail(error, "empty entry table");
  const size_t reserved_end = ((28 + count * 41 + 511) / 512) * 512;
  if (reserved_end > input.size()) return Fail(error, "entry table exceeds image");
  std::vector<std::pair<size_t, size_t>> intervals;
  size_t gnss_count = 0, gnss_start = 0, gnss_size = 0, checksum = 0;
  for (size_t i = 0; i < count; ++i) {
    const size_t row = 28 + i * 41;
    const size_t start = size_t(Le16(input, row + 4)) * 512;
    const size_t size = size_t(Le16(input, row + 6)) * 512;
    if (!size || start < reserved_end || start > input.size() || size > input.size() - start)
      return Fail(error, "entry outside data area");
    intervals.emplace_back(start, start + size);
    Digest hash;
    if (!sha256(input.data() + start, size, hash.data()))
      return Fail(error, "SHA256 failure");
    if (!std::equal(hash.begin(), hash.end(), input.begin() + row + 8))
      return Fail(error, "entry checksum mismatch");
    if (input[row + 40] == 255) {
      ++gnss_count; gnss_start = start; gnss_size = size; checksum = row + 8;
    }
  }
  std::sort(intervals.begin(), intervals.end());
  for (size_t i = 1; i < intervals.size(); ++i)
    if (intervals[i - 1].second > intervals[i].first)
      return Fail(error, "overlapping entries");
  if (gnss_count != 1) return Fail(error, "exactly one GNSS entry required");
  const char path[] = "/nv/item_files/gps/cgps/me/gnss_multiband_configuration";
  std::vector<uint8_t> prefix = {0x02,0x19,0xff,0x18,0x01,0x00,0x38,0x00};
  prefix.insert(prefix.end(), path, path + sizeof(path));
  prefix.insert(prefix.end(), {0x02,0x00,0x05,0x00});
  size_t found = 0, field = 0;
  const size_t end = gnss_start + gnss_size;
  for (size_t cursor = gnss_start; cursor < end;) {
    if (end - cursor < 4) return Fail(error, "truncated GNSS record length");
    const size_t length = Le32(input, cursor);
    if (!length) break;
    if (length < 4 || length > end - cursor)
      return Fail(error, "invalid GNSS record length");
    if (length >= 4 + prefix.size() &&
        std::equal(prefix.begin(), prefix.end(), input.begin() + cursor + 4)) {
      if (length != 4 + prefix.size() + 5)
        return Fail(error, "unsupported multiband record size");
      ++found; field = cursor + 4 + prefix.size();
    }
    cursor += length;
  }
  if (found != 1) return Fail(error, "exactly one multiband record required");
  if (input[field] != 7 || (input[field + 1] != 0 && input[field + 1] != 0x27) ||
      input[field + 2] || input[field + 3] || input[field + 4])
    return Fail(error, "unrecognized multiband value");
  std::vector<uint8_t> canonical(input.begin() + gnss_start, input.begin() + end);
  canonical[field - gnss_start + 1] = 0;
  Digest hash;
  if (!sha256(canonical.data(), canonical.size(), hash.data()))
    return Fail(error, "SHA256 failure");
  if (hash != profile.canonical_gnss)
    return Fail(error, "GNSS entry differs from reviewed template");
  Patch result;
  result.image = input;
  result.field_offset = field; result.checksum_offset = checksum;
  result.image[field + 1] = enable ? 0x27 : 0;
  if (!sha256(result.image.data() + gnss_start, gnss_size, hash.data()))
    return Fail(error, "SHA256 failure");
  std::copy(hash.begin(), hash.end(), result.image.begin() + checksum);
  result.changed = result.image != input;
  *output = std::move(result);
  if (error) error->clear();
  return true;
}
}  // namespace realme_gnss
