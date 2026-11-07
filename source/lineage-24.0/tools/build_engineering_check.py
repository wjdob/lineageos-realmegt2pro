"""Build a project-signed, read-only engineering recovery check ZIP. No device I/O."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,io,json,re,ssl,subprocess,zipfile

ROOT=Path(__file__).resolve().parents[1]

def script(recovery_sha,session):
    if not re.fullmatch('[0-9a-f]{64}',recovery_sha):raise ValueError('full recovery hash required')
    if not re.fullmatch('[a-z0-9-]{1,64}',session):raise ValueError('bounded session identifier required')
    return ('''#!/system/bin/sh
set -eu
[ "$#" = 3 ] || exit 1
case "$1" in 1|2|3) ;; *) exit 1 ;; esac
case "$2" in ''|*[!0-9]*) exit 1 ;; esac
FD="/proc/self/fd/$2"
ui() {
    printf 'ui_print %s\\nui_print\\n' "$*" > "$FD"
    # Recovery's ui_print handler uses PrintOnScreenOnly. Mirror to stderr so
    # the same result is available to read-only host log verification.
    printf '%s\\n' "$*" >&2
}
fail() { ui "ERROR: $*"; exit 1; }
[ "$(id -u)" = 0 ] || fail 'root recovery required'
[ "$(getprop ro.bootmode)" = recovery ] || fail 'recovery required'
[ "$(getprop ro.product.model)" = RMX3301 ] || fail 'model differs'
[ "$(getprop ro.build.version.sdk)" = 37 ] || fail 'SDK differs'
[ "$(getprop ro.boot.vbmeta.device_state)" = unlocked ] || fail 'unlock state differs'
[ "$(getprop ro.lineage.recovery.engineering)" = 1 ] || fail 'engineering image required'
[ "$(getprop ro.adb.secure)" = 1 ] || fail 'ADB authentication required'
[ "$(getprop ro.adb.secure.recovery)" = 1 ] || fail 'recovery authentication required'
SLOT=$(getprop ro.boot.slot_suffix)
case "$SLOT" in _a|_b) ;; *) fail 'unknown slot' ;; esac
BLOCK="/dev/block/by-name/recovery$SLOT"
RESULT=$(sha256sum "$BLOCK") || fail 'recovery hash read failed'
[ "$RESULT" = '@SHA@  '"$BLOCK" ] || fail 'recovery image differs'
ui 'READ_ONLY_CHECK_PASS @SESSION@'
ui 'No mount, partition write, data change or reboot was requested by this script.'
'''.replace('@SHA@',recovery_sha).replace('@SESSION@',session)).encode()

def build(android,signing,out,recovery_sha,session):
    body=script(recovery_sha,session)
    if out.exists():raise ValueError('new output directory required')
    cert=(signing/'releasekey.x509.pem').read_bytes();project=(ROOT/'certs/rmx3301-releasekey.x509.pem').read_bytes()
    cert_der=ssl.PEM_cert_to_DER_cert(cert.decode())
    if cert_der!=ssl.PEM_cert_to_DER_cert(project.decode()):raise ValueError('project signing certificate required')
    out.mkdir(parents=True,exist_ok=False)
    unsigned=out/'unsigned.zip';signed=out/'engineering-read-only-check.zip'
    with zipfile.ZipFile(unsigned,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in [('META-INF/com/google/android/update-binary',body),('META-INF/com/android/otacert',cert)]:
            info=zipfile.ZipInfo(name,(2009,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100755 if name.endswith('update-binary') else 0o100644)<<16
            z.writestr(info,data)
    java=android/'prebuilts/jdk/jdk21/linux-x86/bin/java';jar=android/'prebuilts/sdk/tools/lib/signapk.jar'
    subprocess.run([str(java),'-Xmx256m','-Djava.library.path='+str(android/'prebuilts/sdk/tools/linux/lib64'),
                    '-jar',str(jar),'-w',str(signing/'releasekey.x509.pem'),str(signing/'releasekey.pk8'),str(unsigned),str(signed)],
                   check=True,capture_output=True,timeout=180)
    from verify_signapk_ota import signer_cert
    with zipfile.ZipFile(signed) as z:
        if z.read('META-INF/com/google/android/update-binary')!=body:raise ValueError('signed check body differs')
        verification=signer_cert(signed,z,out,'openssl')
    expected=hashlib.sha256(cert_der).hexdigest()
    if verification['cms_signer_sha256']!=expected or not verification['signer_matches_otacert']:
        raise ValueError('check ZIP signing identity differs')
    digest=hashlib.sha256(signed.read_bytes()).hexdigest()
    report={'created_utc':datetime.now(timezone.utc).isoformat(),'artifact':signed.name,'sha256':digest,
            'bytes':signed.stat().st_size,'expected_recovery_sha256':recovery_sha,'session':session,
            'script_sha256':hashlib.sha256(body).hexdigest(),'signing_certificate_sha256':expected,
            'signature':verification,'builder_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'limits':'Offline signed read-only check package only. It has not run in recovery. Signature/transfer success does not prove installation, ADB return or Android boot. The normal recovery sideload lifecycle has its own metadata/log behavior.'}
    (out/'SHA256SUMS').write_text(digest+'  '+signed.name+'\n');(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('android-tree','signing-dir','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--recovery-sha256',required=True);p.add_argument('--session',required=True);a=p.parse_args()
    r=build(a.android_tree,a.signing_dir,a.out,a.recovery_sha256,a.session)
    print(json.dumps({k:r[k] for k in ('artifact','sha256','bytes')}))

if __name__=='__main__':main()
