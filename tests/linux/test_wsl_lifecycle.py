#!/usr/bin/env python3
"""Run pinned Linux distribution lifecycle on a real non-root WSL2 user."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--kit-a', type=Path, required=True)
    parser.add_argument('--kit-b', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--resume-installed-a', action='store_true')
    parser.add_argument('--complete-installed-a', action='store_true')
    parser.add_argument('--full', action='store_true')
    args = parser.parse_args()
    assert sys.platform == 'linux' and os.getuid() != 0
    assert 'WSL2' in os.uname().release and os.uname().machine == 'x86_64'
    home = Path.home()
    state = home / '.local/share/axiom'
    resuming = args.resume_installed_a or args.complete_installed_a
    if not resuming:
        assert not (state / 'installs/ecosystem/current').exists(), 'preserve existing install'
    args.out.mkdir(parents=True, exist_ok=True)
    records = json.loads((args.out/'commands.json').read_text()) if resuming else []
    if resuming:
        assert any(r['id']=='engine-install-apply' and r['exit_code']==0 for r in records)
    env = dict(os.environ, HOME=str(home), AXIOM_HOME=str(state),
               AXIOM_CLI_INSTALL_ROOT=str(state), PATH='/usr/bin:/bin',
               PYTHONNOUSERSITE='1', PIP_CONFIG_FILE=os.devnull)

    def scrub(value):
        if isinstance(value, str):
            return value.replace(str(home), '<test-home>')
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, dict):
            return {k: '<redacted>' if k.lower() in {'token','password','secret','authorization'}
                    else scrub(v) for k,v in value.items()}
        return value

    def run(name, argv, expected=0, json_body=True, extra=None):
        result = subprocess.run([str(a) for a in argv], env=dict(env, **(extra or {})),
                                capture_output=True, text=True, timeout=300)
        row = {'id':name, 'argv':[str(a) for a in argv], 'exit_code':result.returncode,
               'expected_exit_code':expected, 'stdout':result.stdout, 'stderr':result.stderr}
        records.append(scrub(row))
        (args.out/'commands.json').write_text(json.dumps(records,indent=2)+'\n')
        assert result.returncode == expected, f'{name}: {result.returncode}: {(result.stdout+result.stderr)[-1500:]}'
        if json_body:
            return json.loads(result.stdout if result.stdout.strip() else result.stderr)
        return result

    def digest(body):
        return body.get('plan_digest') or body.get('details',{}).get('plan_digest')

    provisioner = ROOT/'packaging/linux/Provision-McpRuntime.py'
    runtime_root = state/'mcp-runtime'
    native_runtime = [sys.executable,provisioner,'provision','--root',runtime_root,
                      '--version','0.1.0','--source-revision',args.source_revision]
    inputs = {'runtime':'cpython-3.13.15-linux-x64-candidate.tar.gz',
              'wheelhouse':'wheelhouse-linux-x64-py313.tar.gz',
              'wheel':'axiom_mcp-0.1.0-py3-none-any.whl',
              'lock':'container-linux-x64-py313-requirements.txt'}
    for key,name in inputs.items():
        path=args.inputs/name
        native_runtime += ['--'+key,path,'--'+key+'-sha256',sha(path)]
    runtime = run('runtime-status',[sys.executable,provisioner,'status','--root',runtime_root]) if resuming else run('runtime-provision',native_runtime)
    env['PATH'] = str(Path(runtime['python']).parent)+':/usr/bin:/bin'
    sentinel=home/'user-data.txt'
    if resuming:
        previous_query=next((r for r in records if r['id']=='query-watcher-a' and r['exit_code']==0),None)
        if previous_query:
            assert sha(sentinel)==json.loads(previous_query['stdout'])['user_data_sha256']
        else:
            assert sentinel.read_text() == 'K-408 retain non-root user data\n'
    else:
        assert not sentinel.exists(), 'preserve unrelated sentinel'
        sentinel.write_text('K-408 retain non-root user data\n')
    a=args.kit_a/'release/axiom-cli'
    if not resuming:
        plan=run('engine-install-plan',[a,'install','--from',args.kit_a/'release','--dry-run','--json'])
        approval=digest(plan);assert approval
        run('engine-install-apply',[a,'install','--from',args.kit_a/'release','--apply','--approve-digest',approval,'--json'])
    shell=['/bin/sh',args.kit_a/'Install-AxiomCli.sh','--release-set',args.kit_a/'cli-release/release-set.json']
    if not args.complete_installed_a:
        plan=run('cli-install-plan',shell+['--plan','--json'])
        run('cli-install-apply',shell+['--apply','--approve-digest',digest(plan),'--json'])
    installed=home/'.local/bin/axiom-cli'
    run('installed-discovery',[installed,'version','--json'])
    if not args.complete_installed_a:
        run('query-watcher-a',[sys.executable,ROOT/'tests/linux/k406_query_watch.py',
                               '--home',home,'--symbol','K408WatcherA','--setup'])
    if args.complete_installed_a or args.full:
        assert any(r['id']=='query-watcher-a' and r['exit_code']==0 for r in records)
        if not any(r['id']=='installer-boundaries' and r['exit_code']==0 for r in records):
            run('installer-boundaries',['/bin/sh',ROOT/'tests/linux/Invoke-AxiomCliLinuxDistributionTests.sh',
                                   '--cli-binary',args.kit_b/'release/axiom-cli',
                                   '--scratch',home/'axiom-k408/installer-boundaries',
                                   '--json-out',args.out/'installer-report.json'],json_body=False)
        if not any(r['id']=='update-rollback' and r['exit_code']==0 for r in records):
            run('update-negatives',[sys.executable,ROOT/'tests/linux/k408_negative.py',
                                  '--home',home,'--kit',args.kit_b,'--incompatible-kit',args.kit_a,
                                  '--scratch',home/'axiom-k408/corrupt-kit'])
            b=args.kit_b/'release/axiom-cli'
            update_env={'AXIOM_CLI_COMPOSITE_KIT':str(args.kit_b)}
            plan_file=home/'axiom-k408/plan-b.json'
            plan=run('update-plan',[b,'update','plan','--to','0.1.1','--out',plan_file,'--json'],extra=update_env)
            run('update-apply',[b,'update','apply','--plan',plan_file,'--approve-digest',digest(plan),'--json'],extra=update_env)
            run('query-watcher-b',[sys.executable,ROOT/'tests/linux/k406_query_watch.py','--home',home,'--symbol','K408WatcherB'])
            run('update-rollback',[b,'update','rollback','--transaction','previous','--json'],extra=update_env)
            run('query-watcher-rollback',[sys.executable,ROOT/'tests/linux/k406_query_watch.py','--home',home,'--symbol','K408WatcherRestored'])
        installed_core=args.kit_b/'release/axiom'
        uninstall_plan=home/'axiom-k408/engine-uninstall-plan.json'
        plan=run('engine-uninstall-plan',[installed_core,'uninstall','plan','--out',uninstall_plan,'--json'])
        run('engine-uninstall-apply',[installed_core,'uninstall','apply','--plan',uninstall_plan,'--approve-digest',digest(plan),'--json'])
        cli_remove=ROOT/'installers/linux/Uninstall-AxiomCli.sh'
        plan=run('cli-uninstall-plan',['/bin/sh',cli_remove,'--plan','--json'])
        run('cli-uninstall-apply',['/bin/sh',cli_remove,'--apply','--approve-digest',digest(plan),'--json'])
        run('runtime-remove',[sys.executable,provisioner,'remove','--root',runtime_root])
        assert sha(sentinel)==json.loads(next(r for r in records if r['id']=='query-watcher-a')['stdout'])['user_data_sha256']
        assert (home/'demo-repo/src/TokenSource.cs').is_file()
        assert (state/'config/bindings.json').is_file()
        assert not (home/'.local/bin/axiom-cli').exists()
    report={'task_id':'K-408','lane':'wsl2-linux-x64','uid':os.getuid(),
            'kernel':os.uname().release,'runtime':runtime,'commands':records,
            'stage':'complete' if args.complete_installed_a or args.full else 'installed-a',
            'source_base_revision':args.source_revision,'harness_sha256':sha(Path(__file__)),'certified':False}
    (args.out/'native-report.json').write_text(json.dumps(scrub(report),indent=2)+'\n')
    print(json.dumps({'status':report['stage'],'uid':os.getuid(),'command_count':len(records),'certified':False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
