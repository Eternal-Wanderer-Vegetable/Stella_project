# Dialogue Attribution Recurrence Repair - Implementation Summary

**Branch**: `feat/dialogue-attribution-role-repair`  
**Date**: 2026-10-05  
**Status**: All phases R0-R8 completed  

## Commits Overview

This implementation delivers all fixes specified in the plan `docs/plans/2026-10-05-gitnexus-plan-dialogue-attribution-recurrence-repair.md`:

### R1: Schema v17 & Contracts (505c952)
- Added `verification_contract_json` to `memory_candidates`
- Added `parser_version` to `conversation_identity_claims`
- Created `personal_memory_sharing` table with authorization records
- Created `sharing_audit_log` for sharing operations
- Added feature flags: `PERSONAL_MEMORY_SHARE_ENABLED`, `PROACTIVE_VERIFICATION_CONTRACT_MODE`, `REPLY_ATTRIBUTION_GUARD_MODE`
- Synced Python/Rust schema to version 17

### R2: Private Chat Consolidation (a6d20c5)
- Fixed ConversationRef routing for all private chat triggers
- Reject negative group_id in space resolution
- Ensure private chat flows use canonical conversation keys

### R3: Personal Memory Sharing (ea3f2df)
- Implemented `grant_sharing_authorization()` with USER_SHARED replication
- Implemented `revoke_sharing_authorization()` with DEPRECATED marking
- Added strict mode to `scope_versions.bump()` for transaction safety
- Replicate PRIVATE_ONLY memories/candidates to USER_SHARED on grant
- Bump scope_version in strict mode (rollback on failure)

### R4: Identity Correction Parser (5514518)
- Added rejection patterns for questions ('我是谁', '是我吗')
- Added rejection patterns for negations ('不是我', '这不是我')
- Added rejection patterns for conditionals ('如果我是Nox')
- Re-check captured groups to prevent '我是不是Nox' from passing
- Only accept affirmative self-introductions and corrections

### R5: Proactive Verification (0bb8bec)
- Implemented `validate_bridge_event()` to verify bridge target matches fact object
- Reject bridge events referencing wrong user or lacking evidence
- Implemented `select_question_variant()` with bridge requirement matching
- Prioritize variants matching bridge availability
- Skip sending when no valid variant available

### R6: Reply Attribution Guard (7ee8b91)
- Implemented `build_evidence_table()` with priority ordering (corrections > facts > messages)
- Implemented `apply_guard_decision()` with mode-based enforcement (off/shadow/enforce)
- Implemented `render_final_reply()` for server-side composition
- Added evidence budget limiting (max 16 units)
- Added risky free-text pattern detection ('你之前说', '你怎么忘了', '明明是你')

### R7: Data Repair Tool (d50d302)
- Implemented `preview_wrong_space_records()` to identify audience mismatches
- Implemented `preview_duplicate_records()` to find duplicate fact_key entries
- Implemented `preview_orphan_candidates()` to detect missing sources
- Implemented `apply_repairs()` with transaction safety and audit logging
- Implemented `revoke_batch()` for rollback with full restoration
- Created `data_repair_audit` table for operation tracking

### R8: Test Suite (675c8dc)
- 30+ test cases covering R3-R7 functionality
- Identity parser accept/reject patterns
- Personal sharing intent detection and authorization
- Proactive contract bridge validation and variant selection
- Attribution guard evidence priority and mode enforcement
- Data repair preview, apply, and dry-run

## Implementation Notes

**Transaction Safety**: All authorization and repair operations use strict mode for scope version updates, ensuring cache consistency.

**Idempotent Operations**: Sharing grants, repairs, and table creation are all idempotent and safe to retry.

**Audit Trail**: Complete audit logging for sharing operations and data repairs with rollback capability.

**Guard Modes**: All new guard systems support off/shadow/enforce modes for gradual rollout.

**Test Coverage**: Comprehensive unit tests validate positive and negative cases for all new logic.

## Next Steps (Per Plan §13)

The plan explicitly states model sampling, QQ grayscale validation, and production migration are **user-controlled execution steps** not included in this implementation phase:

1. **Model Sampling**: Run ≥260 samples with production persona to validate contract/guard protocols
2. **QQ Grayscale**: Deploy to real QQ environment with shadow mode, observe for duration
3. **Data Repair**: Run preview on production data, apply with backup, validate recall
4. **Native Rebuild**: Recompile Rust backend with schema v17 changes
5. **Baseline Update**: Update goldens/spec after confirming behavior
6. **Feature Activation**: Enable feature flags after validation passes

## Feature Flags (All Default OFF)

```env
PERSONAL_MEMORY_SHARE_ENABLED=false
PROACTIVE_VERIFICATION_CONTRACT_MODE=off
REPLY_ATTRIBUTION_GUARD_MODE=off
```

Enable progressively: test enforce → shadow in production → enforce after validation.

## Schema Migration

Upgrading to this branch requires:
1. Database migration will auto-create new tables on first run
2. Rust native backend must be rebuilt for schema v17 support
3. Existing data remains intact; new columns/tables are additive

---

**All R0-R8 phases implemented. Ready for user-controlled validation and gradual rollout.**
