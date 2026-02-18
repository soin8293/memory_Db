#!/bin/bash
# Runtime policy builder for OpenClaw memory system

# This script analyzes incoming user text and selects relevant policy rules
# to inject into the AI context for that specific interaction.

TEXT=""
while [[ $# -gt 0 ]]; do
  case $F in
    --text)
      TEXT="$2"
      shift 2
      ;;
    *)
      echo "Usage: $0 --text \"user message text\""
      exit 1
      ;;
  esac
done

if [ -z "$TEXT" ]; then
  echo "Error: Text parameter is required"
  exit 1
fi

# Convert text to lowercase for comparison
TEXT_LOWER=$(echo "$TEXT" | tr '[:upper:]' '[:lower:]')

# Initialize array for selected policies
SELECTED_POLICIES=()

# Determine which policy categories apply based on keywords
if [[ "$TEXT_LOWER" =~ (security|password|login|credential|private|secret|confidential) ]]; then
  SELECTED_POLICIES+=("security")
fi

if [[ "$TEXT_LOWER" =~ (memory|remember|recall|history|past|previous|log|record|save|store|forget|delete) ]]; then
  SELECTED_POLICIES+=("memory")
fi

if [[ "$TEXT_LOWER" =~ (project|build|develop|code|program|script|system|tool|api|database|deploy|install|update|upgrade) ]]; then
  SELECTED_POLICIES+=("ops")
fi

if [[ "$TEXT_LOWER" =~ (email|tweet|post|send|message|contact|social|public|external|outside|broadcast|publish) ]]; then
  SELECTED_POLICIES+=("external")
fi

# Limit to maximum 3 policy categories as per guidelines
SELECTED_POLICIES=("${SELECTED_POLICIES[@]:0:3}")

# Output selected policies as comma-separated list
if [ ${#SELECTED_POLICIES[@]} -gt 0 ]; then
  printf '%s\n' "${SELECTED_POLICIES[*]}"
else
  echo "none"
fi