"""Compile the actual reconstructed init source and exercise boot-state guards.

Android property access is mocked; no live device, property service or block device
is used. This does not establish a native Android build or reboot persistence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
SOURCE = 'device/oneplus/sm8450-common/init/init_oplus.cpp'

HEADERS = {
    'android-base/logging.h': '''#pragma once
#include <sstream>
#define LOG(level) std::ostringstream()
''',
    'android-base/properties.h': '''#pragma once
#include <cstring>
#include <string>
namespace android::base {
std::string GetProperty(const std::string&, const std::string&);
}
''',
    'sys/_system_properties.h': '''#pragma once
#include <string>
struct prop_info { std::string name; std::string value; };
const prop_info* __system_property_find(const char*);
int __system_property_update(prop_info*, const char*, unsigned int);
int __system_property_add(const char*, unsigned int, const char*, unsigned int);
''',
}

HARNESS = r'''
#include <map>
#include <string>
#include <stdexcept>
#include <iostream>
#include "sys/_system_properties.h"

static std::map<std::string, prop_info> properties;
static int boot_state_writes;
static const char* key = "ro.boot.vbmeta.device_state";
namespace android::base {
std::string GetProperty(const std::string& name, const std::string& fallback) {
    auto it = properties.find(name);
    return it == properties.end() || it->second.value.empty() ? fallback : it->second.value;
}
}
const prop_info* __system_property_find(const char* name) {
    auto it = properties.find(name);
    return it == properties.end() ? nullptr : &it->second;
}
int __system_property_update(prop_info* info, const char* value, unsigned int size) {
    if (info->name == key) ++boot_state_writes;
    info->value.assign(value, size);
    return 0;
}
int __system_property_add(const char* name, unsigned int size, const char* value, unsigned int len) {
    std::string n(name, size);
    if (n == key) ++boot_state_writes;
    if (properties.count(n)) throw std::runtime_error("duplicate property add");
    properties.emplace(n, prop_info{n, std::string(value, len)});
    return 0;
}
extern void vendor_load_properties();
struct Case { const char* project; const char* prior; const char* verified; bool write; };
int main() {
    const Case cases[] = {
        {"21631", nullptr, "orange", true},
        {"21631", "", "orange", true},
        {"21631", "unlocked", "orange", false},
        {"21631", "locked", "orange", false},
        {"21631", "unexpected", "orange", false},
        {"21631", nullptr, "green", false},
        {"21631", nullptr, "yellow", false},
        {"21631", nullptr, "red", false},
        {"21631", nullptr, "", false},
        {"21631", nullptr, nullptr, false},
        {"21631", nullptr, "ORANGE", false},
        {"21631", nullptr, "orange ", false},
        {"21631", "locked", "green", false},
        {"21631", "unlocked", "green", false},
        {"21631", "", "green", false},
        {"21603", nullptr, "orange", false},
        {"20846", nullptr, "orange", false},
        {"0", nullptr, "orange", false},
        {"216310", nullptr, "orange", false},
    };
    int index = 0;
    for (auto test : cases) {
        properties.clear(); boot_state_writes = 0;
        auto add = [](const char* name, const char* value) {
            if (value) properties.emplace(name, prop_info{name, value});
        };
        add("ro.boot.prjname", test.project);
        add("ro.boot.rf_version", "0");
        add("ro.product.product.device", "RED8ACL1");
        add(key, test.prior);
        add("ro.boot.verifiedbootstate", test.verified);
        vendor_load_properties();
        const auto* result = __system_property_find(key);
        bool valid = test.write ? result && result->value == "unlocked" :
            test.prior ? result && result->value == test.prior : result == nullptr;
        if (!valid || boot_state_writes != (test.write ? 1 : 0)) {
            std::cerr << "boot-state guard failed case " << index << '\n'; return 1;
        }
        if (android::base::GetProperty("ro.boot.verifiedbootstate", "") !=
            std::string(test.verified ? test.verified : "")) {
            std::cerr << "verified boot input changed\n"; return 1;
        }
        ++index;
    }
    std::cout << index << " boot-state guard cases passed\n";
}
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_source(source, compiler=None):
    compiler = Path(compiler or shutil.which('c++') or '/usr/bin/c++').resolve()
    source = Path(source).resolve()
    with tempfile.TemporaryDirectory(prefix='fingerprint-bootstate-', dir=REPO/'tmp') as directory:
        scratch = Path(directory)
        for name, contents in HEADERS.items():
            path = scratch/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        harness = scratch/'harness.cpp'
        harness.write_text(HARNESS)
        executable = scratch/'guards'
        compiled = subprocess.run([str(compiler), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                   '-I', str(scratch), str(source), str(harness), '-o', str(executable)],
                                  capture_output=True, text=True, timeout=60)
        if compiled.returncode:
            raise ValueError('boot-state source compile failed: ' + compiled.stderr)
        result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
        if result.returncode or result.stdout.strip() != '19 boot-state guard cases passed':
            raise ValueError('boot-state behavioral guard failed: ' + result.stderr + result.stdout)
    return {'state': 'passed', 'source_sha256': sha(source), 'compiler_sha256': sha(compiler),
            'compiler_version': subprocess.check_output([str(compiler), '--version'], text=True).splitlines()[0],
            'cases_passed': 19, 'harness_sha256': hashlib.sha256(HARNESS.encode()).hexdigest(),
            'tool_sha256': sha(Path(__file__)),
            'limits': 'Actual init source executed with mocked Android property APIs; not a native Android build, HAL test, reboot or enrollment proof.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-tree', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    source = args.source_tree/SOURCE
    recipe = json.loads((REPO/'tools/build/recipe-23.2.json').read_text())
    binding = next(row for row in recipe['files'] if row['path'] == SOURCE)
    if sha(source) != binding['canonical_sha256']:
        raise ValueError('boot-state source differs from reviewed recipe')
    report = check_source(source)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
