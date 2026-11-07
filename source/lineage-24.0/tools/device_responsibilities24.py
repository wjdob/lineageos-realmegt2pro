"""Inspect device-specific power and SIM service responsibilities in target-files.

These checks validate configuration and delivery. They do not execute hardware.
"""
import re
import stat
import xml.etree.ElementTree as ET
import zipfile


def check(package):
    issues = []
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate target-files member')

        def regular(name):
            if name not in names:
                issues.append(name + ': missing')
                return None
            if stat.S_ISLNK(archive.getinfo(name).external_attr >> 16):
                issues.append(name + ': unexpected symlink')
                return None
            return archive.read(name)

        power = regular('VENDOR/etc/powerhint.xml')
        targets = []
        if power is not None:
            tree = ET.fromstring(power)
            targets = sorted({n.get('Target', '') for n in tree.iter('Config')
                              if n.get('Enable', '').lower() == 'true'})
            if 'taro' not in targets:
                issues.append('power hints: no enabled taro configuration for SM8450')

        instances = []
        registrations = set()
        for name in names:
            if (name.startswith(('VENDOR/etc/vintf/', 'ODM/etc/vintf/'))
                    and name.endswith('.xml')):
                tree = ET.fromstring(archive.read(name))
                for hal in tree.findall('hal'):
                    if hal.findtext('name') != 'android.hardware.secure_element':
                        continue
                    instances.extend(n.text or '' for n in hal.findall('fqname'))
                    instances.extend(n.text or '' for n in hal.findall('interface/instance'))
                    if hal.get('format') != 'hidl' or hal.findtext('transport') != 'hwbinder':
                        continue
                    for fqname in hal.findall('fqname'):
                        match = re.fullmatch(r'@1\.2::ISecureElement/(SIM1|SIM2|eSE1)', fqname.text or '')
                        if match:
                            registrations.add(match.group(1))
                    # Stock may use version/interface syntax instead of fqname.
                    if '1.2' in [n.text for n in hal.findall('version')]:
                        for interface in hal.findall('interface'):
                            if interface.findtext('name') == 'ISecureElement':
                                registrations.update(n.text for n in interface.findall('instance'))
        # The restored .1410 cohort includes both UICC instances and the eSE
        # provider. The latter aborts during registration when eSE1 is absent.
        # These match accepted23b; presence of SIM1 alone is insufficient.
        required = {'SIM1', 'SIM2', 'eSE1'}
        for instance in sorted(required - registrations):
            issues.append('secure element: missing ' + instance + ' VINTF registration')

        service = 'ODM/bin/hw/vendor.qti.secure_element@1.2-service'
        implementation = 'ODM/lib64/android.hardware.secure_element@1.0-impl.so'
        for name in (service, implementation):
            regular(name)
        rc = regular('ODM/etc/init/vendor.qti.secure_element@1.2-service.rc')
        if rc is not None:
            text = rc.decode()
            declaration = r'^service\s+secureelement-hal_1_2\s+/odm/bin/hw/vendor\.qti\.secure_element@1\.2-service\s*$'
            if not re.search(declaration, text, re.M):
                issues.append('secure element: missing matching init service declaration')
            if not re.search(r'^\s+class\s+hal\s*$', text, re.M):
                issues.append('secure element: init service is outside the expected HAL class')

    return {'passed': not issues, 'issues': issues, 'enabled_power_targets': targets,
            'secure_element_instances': instances,
            'required_secure_element_instances': sorted(required),
            'limits': 'Static taro power selection and matching SIM1/SIM2/eSE1 service/implementation/init/VINTF delivery only. No performance, card access, NFC payment or full hardware claim.'}
