#!/usr/bin/env bash
set -euo pipefail

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

PROJECT_DIR="$TMP_DIR/project"
mkdir -p "$PROJECT_DIR/build/dependabot-tools"
cp "$(dirname "$0")/../gather-deps.sh" "$PROJECT_DIR/gather-deps.sh"
chmod +x "$PROJECT_DIR/gather-deps.sh"

cat > "$PROJECT_DIR/gradlew" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "-q" ] && [ "$2" = "--console=plain" ] && [ "$3" = "projects" ]; then
  cat <<'OUT'

------------------------------------------------------------
Root project 'demo'
------------------------------------------------------------

Root project 'demo'
+--- Project ':app'
\--- Project ':lib'

Included builds
+--- Included build ':build-logic'
\--- Included build ':tooling'
OUT
  exit 0
fi

if [ "$1" = "-q" ] && [ "$2" = "--console=plain" ] && [ "$3" = ":build-logic:projects" ]; then
  cat <<'OUT'
Project ':'
+--- Project ':conventions'
\--- Project ':checks'
OUT
  exit 0
fi

if [ "$1" = "-q" ] && [ "$2" = "--console=plain" ] && [ "$3" = ":tooling:projects" ]; then
  cat <<'OUT'
Project ':'
\--- Project ':deps'
OUT
  exit 0
fi

if [ "$1" = "--console=plain" ]; then
  shift
  printf "%s\n" "$@" > "$PWD/build/dependabot-tools/tasks.log"
  cat <<'OUT'
> Task :app:dependencies
dummy
OUT
  exit 0
fi

echo "unexpected args: $*" >&2
exit 1
EOF
chmod +x "$PROJECT_DIR/gradlew"

"$PROJECT_DIR/gather-deps.sh" "$PROJECT_DIR" "$PROJECT_DIR/build/dependabot-tools/gather-deps.txt" >/dev/null

MODULES_FILE="$PROJECT_DIR/build/dependabot-tools/modules.txt"
TASKS_LOG="$PROJECT_DIR/build/dependabot-tools/tasks.log"

grep -qx ":app" "$MODULES_FILE"
grep -qx ":lib" "$MODULES_FILE"
grep -qx ":build-logic" "$MODULES_FILE"
grep -qx ":build-logic:conventions" "$MODULES_FILE"
grep -qx ":build-logic:checks" "$MODULES_FILE"
grep -qx ":tooling" "$MODULES_FILE"
grep -qx ":tooling:deps" "$MODULES_FILE"

grep -qx "buildEnvironment" "$TASKS_LOG"
grep -qx ":app:dependencies" "$TASKS_LOG"
grep -qx ":build-logic:dependencies" "$TASKS_LOG"
grep -qx ":build-logic:conventions:dependencies" "$TASKS_LOG"
grep -qx ":tooling:deps:dependencies" "$TASKS_LOG"

echo "ok"
