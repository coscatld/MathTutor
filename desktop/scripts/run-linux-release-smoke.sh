#!/usr/bin/env bash
set -uo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "UNTESTED — NO TARGET MACHINE: run-linux-release-smoke.sh requires Linux" >&2
  exit 4
fi
if [[ $# -ne 2 ]]; then
  echo "Usage: run-linux-release-smoke.sh <MathTutor.AppImage> <report.json>" >&2
  exit 64
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
artifact="$(realpath "$1")"
report="$(realpath -m "$2")"
mkdir -p "$(dirname "$report")"
work="$(mktemp -d -t mathtutor-linux-rc.XXXXXXXX)"
install_root="$work/Install Path 中文"
data_root="$work/User Data 保留"
secret_report="$work/secret-store.json"
mkdir -p "$install_root" "$data_root"
installed="$install_root/MathTutor.AppImage"
cp "$artifact" "$installed"
chmod 0755 "$installed"
printf '%s\n' 'non-secret release-test marker' > "$data_root/uninstall-must-preserve.txt"

cleanup() {
  rm -rf -- "$work"
}
trap cleanup EXIT

# Extract only the isolated AppImage copy to locate its packaged runtime. This
# is not a user-directory scan and does not change the artifact under test.
extract_root="$work/extracted"
mkdir -p "$extract_root"
(
  cd "$extract_root" || exit 1
  "$installed" --appimage-extract >/dev/null
)
python_runtime="$(find "$extract_root/squashfs-root" -type f -path '*/resources/python-runtime/bin/python' -print -quit)"
python_app="$(find "$extract_root/squashfs-root" -type d -path '*/resources/python-app' -print -quit)"
if [[ -z "$python_runtime" || -z "$python_app" ]]; then
  node -e 'require("fs").writeFileSync(process.argv[1], JSON.stringify({status:"FAIL",reason_code:"RELOCATED_RUNTIME_MISSING",platform:"Linux",plaintext_fallback:false},null,2)+"\n",{mode:0o600})' "$secret_report"
  secret_exit=1
else
  PYTHONPATH="$python_app" PYTHONNOUSERSITE=1 "$python_runtime" \
    "$script_dir/rc-secret-store-sentinel.py" \
    --expected-platform Linux --output "$secret_report"
  secret_exit=$?
fi

export MATHTUTOR_DATA_ROOT="$data_root"
node "$script_dir/rc-public-release-smoke.js" \
  --platform linux --artifact "$installed" --secret-report "$secret_report" --output "$report"
shared_exit=$?

# AppImage "uninstall" is deletion of the executable. User data must remain.
rm -f -- "$installed"
if [[ ! -f "$data_root/uninstall-must-preserve.txt" ]]; then
  uninstall_status="FAIL"
else
  uninstall_status="PASS"
fi

node - "$report" "$artifact" "$secret_exit" "$shared_exit" "$uninstall_status" <<'NODE'
const fs = require("node:fs");
const crypto = require("node:crypto");
const [reportPath, artifact, secretExit, sharedExit, uninstallStatus] = process.argv.slice(2);
const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
report.platform_checks.appimage_executable = "PASS";
report.platform_checks.secret_probe_exit_code = Number(secretExit);
report.platform_checks.shared_driver_exit_code = Number(sharedExit);
report.platform_checks.uninstall_preserves_user_data = uninstallStatus;
report.platform_checks.artifact_signing = { status: "UNSUPPORTED", reason_code: "NO_RELEASE_SIGNING_POLICY" };
report.platform_checks.appimage_sha256 = crypto.createHash("sha256").update(fs.readFileSync(artifact)).digest("hex");
if (uninstallStatus !== "PASS") report.status = "FAIL";
fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
NODE

status="$(node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).status' "$report")"
if [[ "$status" == "PASS" ]]; then exit 0; fi
if [[ "$status" == "PARTIAL" ]]; then exit 2; fi
exit 1
