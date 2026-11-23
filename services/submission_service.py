"""User-defined document roles and deterministic packet completeness checks."""
import copy

PROFILES = {
    'Custom packet': [],
    'Application packet': [{'role': 'application', 'minimum': 1}, {'role': 'identity', 'minimum': 1},
                           {'role': 'certificate', 'minimum': 1}],
    'Reimbursement packet': [{'role': 'claim', 'minimum': 1}, {'role': 'receipt', 'minimum': 1}],
    'Client packet': [{'role': 'cover', 'minimum': 1}, {'role': 'supporting', 'minimum': 1}],
}
ROLES = ['unassigned', 'application', 'identity', 'certificate', 'claim', 'receipt', 'cover', 'supporting']


def validate_requirements(rows):
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError('Use at most 100 checklist entries.')
    result, seen = [], set()
    for row in rows:
        role = str(row.get('role', '')).strip().lower()
        minimum = row.get('minimum', 1)
        if not role or len(role) > 80 or role in seen or isinstance(minimum, bool) or not isinstance(minimum, int) or not 1 <= minimum <= 1000:
            raise ValueError('Each role needs a unique name and a minimum from 1 to 1000.')
        seen.add(role)
        result.append({'role': role, 'minimum': minimum})
    return result


def inspect_packet(document):
    requirements = validate_requirements(document.get('requirements', []))
    used = {page['asset'] for page in document['pages']}
    counts = {}
    for key in used:
        role = document['assets'][key].get('role', 'unassigned')
        counts[role] = counts.get(role, 0) + 1
    checks = [{'name': 'Required document: ' + row['role'],
               'passed': counts.get(row['role'], 0) >= row['minimum'],
               'detail': f"Required {row['minimum']}; found {counts.get(row['role'], 0)} document(s)"}
              for row in requirements]
    seen, duplicates = set(), []
    for index, page in enumerate(document['pages']):
        asset = document['assets'][page['asset']]
        fingerprint = (asset.get('source_hash', asset['pdf_hash']), page['page'])
        if fingerprint in seen:
            duplicates.append(index + 1)
        seen.add(fingerprint)
    return {'passed': all(row['passed'] for row in checks), 'checks': checks,
            'duplicates': duplicates, 'counts': counts}


def suggested_order(document):
    roles = [row['role'] for row in validate_requirements(document.get('requirements', []))]
    rank = {role: index for index, role in enumerate(roles)}
    return [page['id'] for page in sorted(document['pages'],
        key=lambda page: rank.get(document['assets'][page['asset']].get('role'), len(rank)))]
