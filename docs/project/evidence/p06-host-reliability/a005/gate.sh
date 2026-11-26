set -euo pipefail
case "$PLAN_RESULT:$PLAN_RUN:$SETUP_RESULT:$BUILD_RESULT:$TESTS_RESULT" in
  success:true:success:success:success)
    echo "CI complete (tests: success)."
    ;;
  success:false:skipped:skipped:skipped)
    echo "CI complete (no test cells planned)."
    ;;
  *)
    printf '::error::Unexpected CI results: plan=%s run=%s setup=%s build=%s tests=%s\n' \
      "$PLAN_RESULT" "$PLAN_RUN" "$SETUP_RESULT" "$BUILD_RESULT" "$TESTS_RESULT"
    exit 1
    ;;
esac
