#pragma once
#include "GnssNvbkMigration.h"
#include <array>
#include <memory>
#include <string>

namespace realme_gnss {
// Fixed two-partition backend. Journal() durably records the exact inverse ranges
// and full before/after hashes in a small private undo journal. That supplement
// does not replace the required complete off-device backups before first use.
// Paths must come from BootControlInterface's static-partition resolver. Only
// the two exact by-name labels are accepted; no arbitrary device path is exposed.
std::unique_ptr<MigrationIO> CreatePosixMigrationIO(
    Sha256 sha256, const std::array<std::string, 2>& paths);
}  // namespace realme_gnss
