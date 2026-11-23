"""Sign Windows artifacts with an installed identity, or verify cloud-signed artifacts."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def find_signtool():
    compiler=shutil.which('signtool')
    if not compiler:
        root=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Windows Kits/10/bin'
        candidates=sorted(root.glob('*/x64/signtool.exe'),reverse=True)
        compiler=str(candidates[0]) if candidates else None
    if not compiler:raise RuntimeError('Install the Windows SDK signing tools.')
    return compiler


def verify_signature(path,expected_thumbprint=''):
    shell=shutil.which('pwsh') or shutil.which('powershell')
    if not shell:raise RuntimeError('PowerShell is required for Authenticode verification.')
    result=subprocess.run([shell,'-NoProfile','-NonInteractive','-File',str(ROOT/'packaging/verify-windows-signature.ps1'),
        '-ArtifactPath',str(Path(path).resolve()),'-ExpectedThumbprint',expected_thumbprint],
        capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
    return json.loads(result.stdout.lstrip('\ufeff').strip())


def sign(path,required=False,provider='auto',verify_only=False):
    path=Path(path)
    if not path.is_file():raise FileNotFoundError(path)
    if provider not in ('auto','unsigned','certificate','azure'):
        raise ValueError('Choose unsigned, certificate, or azure signing.')
    identity=os.environ.get('ODT_WINDOWS_CERT_SHA1','').strip()
    if provider=='auto':provider='certificate' if identity else 'unsigned'
    if provider=='unsigned':
        if required:raise RuntimeError('A Windows signing identity or cloud provider must be configured.')
        return {'artifact':str(path),'provider':provider,'status':'unsigned','reason':'No Windows signing identity selected'}
    if platform.system()!='Windows':raise RuntimeError('Windows signing and verification require a Windows runner.')
    if provider=='azure' and not verify_only:
        raise RuntimeError('Run the Azure Artifact Signing action first, then use --provider azure --verify-only.')
    if not verify_only:
        if not identity:raise RuntimeError('Configure ODT_WINDOWS_CERT_SHA1 for the installed signing identity.')
        subprocess.run([find_signtool(),'sign','/fd','SHA256','/td','SHA256','/tr','http://timestamp.digicert.com',
            '/sha1',identity,str(path.resolve())],check=True)
    details=verify_signature(path,identity if provider=='certificate' else '')
    return {'artifact':str(path),'provider':provider,'status':'signed-and-verified',**details}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('artifact',type=Path)
    parser.add_argument('--provider',choices=['auto','unsigned','certificate','azure'],default='auto')
    parser.add_argument('--verify-only',action='store_true');parser.add_argument('--required',action='store_true')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    try:
        result=sign(args.artifact,args.required,args.provider,args.verify_only)
    except Exception as error:
        result={'artifact':str(args.artifact),'provider':args.provider,'status':'failed','error':str(error)}
        if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n')
        raise
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
