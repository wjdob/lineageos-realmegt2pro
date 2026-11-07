"""Exercise the actual RMX3301 health subclass with mocked HAL/property boundaries.

This checks units, polarity, device scope, both HAL paths and error propagation;
it does not establish native Android compilation or live corrected reporting.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

REPO = Path(__file__).resolve().parents[1]
SOURCE = 'vendor/qcom/opensource/healthd-ext/aidl/main.cpp'
PREFIX = r'''
#include <cstdint>
#include <limits>
#include <sstream>
#include <string>
#include <stdexcept>
#include <iostream>
#define LOG(level) std::ostringstream()
constexpr int EX_ILLEGAL_STATE = -5;
static std::string project;
namespace android::base {
std::string GetProperty(const std::string& key, const std::string&) {
    if (key != "ro.boot.prjname") throw std::runtime_error("wrong project property");
    return project;
}
}
namespace ndk {
struct ScopedAStatus {
    int code;
    bool isOk() const { return code == 0; }
    static ScopedAStatus fromExceptionCode(int code) { return {code}; }
};
}
namespace aidl::android::hardware::health {
struct HealthInfo { int32_t batteryCurrentMicroamps, batteryCurrentAverageMicroamps; int capacity; };
}
using aidl::android::hardware::health::HealthInfo;
class Health {
  public:
    int32_t now = 0, average = 0;
    int error = 0;
    virtual ~Health() = default;
    virtual ndk::ScopedAStatus getCurrentNowMicroamps(int32_t* out) { *out = now; return {error}; }
    virtual ndk::ScopedAStatus getCurrentAverageMicroamps(int32_t* out) { *out = average; return {error}; }
    HealthInfo info() { HealthInfo result{now, average, 73}; UpdateHealthInfo(&result); return result; }
  protected:
    virtual void UpdateHealthInfo(HealthInfo*) {}
};
'''
SUFFIX = r'''
static void require(bool good, const char* message) { if (!good) throw std::runtime_error(message); }
int main() {
    int cases = 0;
    for (const auto& name : {"21631", "", "21632", "216310"}) {
        project = name;
        Rmx3301Health service;
        for (int32_t raw : {-2147483, -673, -1, 0, 1, 153, 2147483}) {
            service.now = raw; service.average = -raw;
            const int32_t expected = project == "21631" ? static_cast<int32_t>(-1000LL * raw) : raw;
            int32_t result = 999;
            require(service.getCurrentNowMicroamps(&result).isOk() && result == expected, "direct now");
            require(service.getCurrentAverageMicroamps(&result).isOk() && result == -expected, "direct average");
            const auto info = service.info();
            require(info.batteryCurrentMicroamps == expected && info.batteryCurrentAverageMicroamps == -expected, "health update");
            require(info.capacity == 73, "capacity changed");
            ++cases;
        }
        for (int32_t raw : {std::numeric_limits<int32_t>::min(), -2147484, 2147484, std::numeric_limits<int32_t>::max()}) {
            service.now = raw; service.average = raw;
            int32_t result = 0;
            const auto status = service.getCurrentNowMicroamps(&result);
            const auto average = service.getCurrentAverageMicroamps(&result);
            const auto info = service.info();
            if (project == "21631") {
                require(status.code == EX_ILLEGAL_STATE && average.code == EX_ILLEGAL_STATE, "overflow status");
                require(info.batteryCurrentMicroamps == 0 && info.batteryCurrentAverageMicroamps == 0, "overflow health fallback");
            } else {
                require(status.isOk() && average.isOk() && result == raw, "unrelated direct changed");
                require(info.batteryCurrentMicroamps == raw && info.batteryCurrentAverageMicroamps == raw, "unrelated update changed");
            }
            ++cases;
        }
        service.error = -7; service.now = -673; service.average = 153;
        int32_t result = 0;
        require(service.getCurrentNowMicroamps(&result).code == -7 && result == -673, "now error changed");
        require(service.getCurrentAverageMicroamps(&result).code == -7 && result == 153, "average error changed");
        ++cases;
    }
    std::cout << cases << " health current cases passed\n";
}
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_source(source):
    source = Path(source)
    text = source.read_text()
    if text.count('make<Rmx3301Health>(gInstanceName') != 1:
        raise ValueError('HAL must instantiate the corrected health subclass')
    start = text.index('class Rmx3301Health : public Health {')
    end = text.index('\nstatic constexpr const char* gInstanceName', start)
    compiler = Path(shutil.which('c++')).resolve()
    with tempfile.TemporaryDirectory(prefix='health-current-', dir=REPO/'tmp') as directory:
        scratch = Path(directory)
        harness = scratch/'harness.cpp'
        harness.write_text(PREFIX + text[start:end] + SUFFIX)
        binary = scratch/'check'
        compiled = subprocess.run([str(compiler), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                   '-fsanitize=undefined', '-fno-sanitize-recover=all', str(harness), '-o', str(binary)],
                                  capture_output=True, text=True, timeout=60)
        if compiled.returncode:
            raise ValueError('health source compile failed: ' + compiled.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        if result.returncode or result.stdout.strip() != '48 health current cases passed':
            raise ValueError('health source behavior failed: ' + result.stdout + result.stderr)
    return dict(state='passed', cases_passed=48, source_sha256=sha(source),
                compiler_sha256=sha(compiler), compiler_version=subprocess.check_output([str(compiler), '--version'], text=True).splitlines()[0],
                harness_sha256=hashlib.sha256((PREFIX+SUFFIX).encode()).hexdigest(), tool_sha256=sha(__file__),
                limits='Actual subclass compiled/executed with mocked HAL/property boundaries and UBSan; not native Android build or corrected live reporting.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-tree', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--target-files', type=Path)
    args = parser.parse_args()
    source = args.source_tree/SOURCE
    recipe = json.loads((REPO/'tools/build/recipe-23.2.json').read_text())
    binding = next(row for row in recipe['files'] if row['path'] == SOURCE)
    if sha(source) != binding['canonical_sha256']:
        raise ValueError('health source differs from recipe')
    report = check_source(source)
    if args.target_files:
        contract_path = REPO/'configs/health-current-23.2.json'
        contract = json.loads(contract_path.read_text())
        checked = {}
        with zipfile.ZipFile(args.target_files) as archive:
            for name, expected in contract['modules'].items():
                if archive.namelist().count(name) != 1:
                    raise ValueError('missing or duplicate reviewed gauge module: ' + name)
                actual = hashlib.sha256(archive.read(name)).hexdigest()
                if actual != expected:
                    raise ValueError('gauge module changed; renew current conversion review: ' + name)
                checked[name] = actual
        report['gauge_modules'] = checked
        report['target_files_sha256'] = sha(args.target_files)
        report['contract_sha256'] = sha(contract_path)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
