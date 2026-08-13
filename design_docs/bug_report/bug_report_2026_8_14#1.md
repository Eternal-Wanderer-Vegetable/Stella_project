# test(3.10)

Run pytest tests/ \
  pytest tests/ \
    -v \
    --cov=. \
    --cov-branch \
    -n auto \
    --dist loadgroup
  shell: /usr/bin/bash -e {0}
  env:
    pythonLocation: /opt/hostedtoolcache/Python/3.10.20/x64
    PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.10.20/x64/lib/pkgconfig
    Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.10.20/x64
    Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.10.20/x64
    Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.10.20/x64
    LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.10.20/x64/lib
    COVERAGE_FILE: cov-3.10
============================= test session starts ==============================
platform linux -- Python 3.10.20, pytest-9.1.1, pluggy-1.6.0 -- /opt/hostedtoolcache/Python/3.10.20/x64/bin/python
cachedir: .pytest_cache
rootdir: /home/runner/work/Stella_project/Stella_project
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2, xdist-3.8.0
created: 4/4 workers
4 workers [219 items]

scheduling tests via LoadGroupScheduling

tests/test_benchmark_and_log.py::test_load_cases_list_and_broken 
tests/test_benchmark_and_log.py::test_load_cases_missing_dir 
tests/test_benchmark_and_log.py::test_evaluate_case_basic 
tests/test_benchmark_and_log.py::test_evaluate_case_forbidden_reported 
[gw0] [  0%] PASSED tests/test_benchmark_and_log.py::test_load_cases_missing_dir 
tests/test_benchmark_and_log.py::test_evaluate_case_expected_in_behavior_constraints 
[gw1] [  0%] PASSED tests/test_benchmark_and_log.py::test_load_cases_list_and_broken 
tests/test_benchmark_and_log.py::test_run_benchmark_empty_dir 
[gw1] [  1%] PASSED tests/test_benchmark_and_log.py::test_run_benchmark_empty_dir 
tests/test_benchmark_and_log.py::test_consolidation_log_handles_error 
[gw1] [  1%] PASSED tests/test_benchmark_and_log.py::test_consolidation_log_handles_error 
tests/test_bot_self_source.py::test_record_message_persists_bot_self 
[gw0] [  2%] PASSED tests/test_benchmark_and_log.py::test_evaluate_case_expected_in_behavior_constraints 
tests/test_benchmark_and_log.py::test_consolidation_log_append_and_create 
[gw0] [  2%] PASSED tests/test_benchmark_and_log.py::test_consolidation_log_append_and_create 
[gw1] [  3%] PASSED tests/test_bot_self_source.py::test_record_message_persists_bot_self 
tests/test_bot_self_source.py::test_fetch_next_messages_bot_self_marked_and_excluded 
[gw3] [  3%] PASSED tests/test_benchmark_and_log.py::test_evaluate_case_forbidden_reported 
[gw2] [  4%] PASSED tests/test_benchmark_and_log.py::test_evaluate_case_basic 
tests/test_bot_self_source.py::test_mixed_window_three_markers 
tests/test_benchmark_and_log.py::test_run_benchmark_sums_metrics 
tests/test_benchmark_and_log.py::test_evaluate_case_over_recall_respects_max_retrieved 
[gw1] [  4%] PASSED tests/test_bot_self_source.py::test_fetch_next_messages_bot_self_marked_and_excluded 
[gw0] [  5%] PASSED tests/test_bot_self_source.py::test_mixed_window_three_markers 
tests/test_candidate_reinforcement.py::test_same_fact_accumulates_instead_of_duplicating 
tests/test_bot_self_source.py::test_write_memory_candidates_drops_bot_self_candidate 
[gw2] [  5%] PASSED tests/test_benchmark_and_log.py::test_run_benchmark_sums_metrics 
tests/test_candidate_reinforcement.py::test_similar_wording_counts_as_same_fact 
[gw3] [  5%] PASSED tests/test_benchmark_and_log.py::test_evaluate_case_over_recall_respects_max_retrieved 
tests/test_candidate_reinforcement.py::test_unrelated_facts_stay_separate 
[gw1] [  6%] PASSED tests/test_bot_self_source.py::test_write_memory_candidates_drops_bot_self_candidate 
[gw0] [  6%] PASSED tests/test_candidate_reinforcement.py::test_same_fact_accumulates_instead_of_duplicating 
tests/test_candidate_reinforcement.py::test_source_kinds_accumulate_across_observations 
tests/test_candidate_reinforcement.py::test_same_content_different_users_stay_separate 
[gw2] [  7%] PASSED tests/test_candidate_reinforcement.py::test_similar_wording_counts_as_same_fact 
tests/test_candidate_reinforcement.py::test_first_seen_at_not_refreshed_on_reoccurrence 
[gw3] [  7%] PASSED tests/test_candidate_reinforcement.py::test_unrelated_facts_stay_separate 
tests/test_candidate_reinforcement.py::test_confidence_capped_at_one 
[gw0] [  8%] PASSED tests/test_candidate_reinforcement.py::test_same_content_different_users_stay_separate 
[gw1] [  8%] PASSED tests/test_candidate_reinforcement.py::test_source_kinds_accumulate_across_observations 
[gw2] [  9%] PASSED tests/test_candidate_reinforcement.py::test_first_seen_at_not_refreshed_on_reoccurrence 
tests/test_candidate_reinforcement.py::test_gate1_high_confidence_promotes_immediately 
tests/test_candidate_reinforcement.py::test_gate1_mid_confidence_promotes_after_reoccurrence 
tests/test_candidate_reinforcement.py::test_gate1_mid_confidence_passive_single_observation_waits 
[gw1] [  9%] PASSED tests/test_candidate_reinforcement.py::test_gate1_high_confidence_promotes_immediately 
[gw2] [ 10%] PASSED tests/test_candidate_reinforcement.py::test_gate1_mid_confidence_promotes_after_reoccurrence 
tests/test_candidate_reinforcement.py::test_gate1_importance_alone_does_not_promote 
[gw2] [ 10%] PASSED tests/test_candidate_reinforcement.py::test_gate1_importance_alone_does_not_promote 
[gw0] [ 10%] PASSED tests/test_candidate_reinforcement.py::test_gate1_mid_confidence_passive_single_observation_waits 
tests/test_candidate_reinforcement.py::test_gate1_low_confidence_never_promotes_even_with_at_mention 
[gw1] [ 11%] PASSED tests/test_candidate_reinforcement.py::test_gate1_low_confidence_never_promotes_even_with_at_mention 
tests/test_candidate_reinforcement.py::test_gate1_trivial_importance_blocked 
tests/test_candidate_reinforcement.py::test_reoccurrence_eventually_promotes_end_to_end 
[gw0] [ 11%] PASSED tests/test_candidate_reinforcement.py::test_gate1_trivial_importance_blocked 
tests/test_candidate_reinforcement.py::test_has_at_mention_tolerates_garbage 
tests/test_candidate_reinforcement.py::test_stale_observing_candidate_rejected 
[gw1] [ 12%] PASSED tests/test_candidate_reinforcement.py::test_has_at_mention_tolerates_garbage 
tests/test_candidate_reinforcement.py::test_quota_score_handles_garbage 
[gw1] [ 12%] PASSED tests/test_candidate_reinforcement.py::test_quota_score_handles_garbage 
tests/test_candidate_reinforcement.py::test_quota_enforce_archives_weakest 
[gw3] [ 13%] PASSED tests/test_candidate_reinforcement.py::test_confidence_capped_at_one 
tests/test_candidate_reinforcement.py::test_gate1_at_mention_promotes_single_shot 
[gw3] [ 13%] PASSED tests/test_candidate_reinforcement.py::test_gate1_at_mention_promotes_single_shot 
tests/test_compressor.py::test_weekly_no_active_memories 
[gw3] [ 14%] PASSED tests/test_compressor.py::test_weekly_no_active_memories 
tests/test_compressor.py::test_weekly_merges_duplicates 
[gw1] [ 14%] PASSED tests/test_candidate_reinforcement.py::test_quota_enforce_archives_weakest 
[gw0] [ 15%] PASSED tests/test_candidate_reinforcement.py::test_stale_observing_candidate_rejected 
tests/test_candidate_reinforcement.py::test_quota_is_per_user_and_per_group 
[gw3] [ 15%] PASSED tests/test_compressor.py::test_weekly_merges_duplicates 
tests/test_candidate_reinforcement.py::test_quota_dry_run_does_not_archive 
[gw2] [ 15%] PASSED tests/test_candidate_reinforcement.py::test_reoccurrence_eventually_promotes_end_to_end 
tests/test_compressor.py::test_weekly_atomizes_long_memory 
tests/test_candidate_reinforcement.py::test_quota_score_prefers_confirmed_and_recent 
[gw2] [ 16%] PASSED tests/test_candidate_reinforcement.py::test_quota_score_prefers_confirmed_and_recent 
tests/test_consolidation_prompt.py::test_no_fabrication_clauses_present 
[gw2] [ 16%] PASSED tests/test_consolidation_prompt.py::test_no_fabrication_clauses_present 
tests/test_consolidation_prompt.py::test_attribution_clause_present 
[gw2] [ 17%] PASSED tests/test_consolidation_prompt.py::test_attribution_clause_present 
tests/test_consolidation_prompt.py::test_bot_self_clause_present 
[gw2] [ 17%] PASSED tests/test_consolidation_prompt.py::test_bot_self_clause_present 
tests/test_consolidation_prompt.py::test_empty_array_permission_present 
[gw3] [ 18%] PASSED tests/test_compressor.py::test_weekly_atomizes_long_memory 
[gw2] [ 18%] PASSED tests/test_consolidation_prompt.py::test_empty_array_permission_present 
tests/test_consolidation_prompt.py::test_describes_whom_criterion_present 
tests/test_compressor.py::test_split_into_fragments_and_store 
[gw2] [ 19%] PASSED tests/test_consolidation_prompt.py::test_describes_whom_criterion_present 
tests/test_consolidation_prompt.py::test_no_negative_example_blocks 
[gw2] [ 19%] PASSED tests/test_consolidation_prompt.py::test_no_negative_example_blocks 
[gw1] [ 20%] PASSED tests/test_candidate_reinforcement.py::test_quota_is_per_user_and_per_group 
[gw0] [ 20%] PASSED tests/test_candidate_reinforcement.py::test_quota_dry_run_does_not_archive 
tests/test_consolidation_prompt.py::test_format_fills_placeholders 
tests/test_compressor.py::test_maybe_compress_light_runs_once 
[gw3] [ 21%] PASSED tests/test_compressor.py::test_split_into_fragments_and_store 
[gw2] [ 21%] PASSED tests/test_consolidation_prompt.py::test_format_fills_placeholders 
tests/test_compressor.py::test_maybe_compress_skips_when_cooled_down 
tests/test_consolidator_core.py::test_parse_json_variants 
tests/test_consolidation_prompt.py::test_no_hard_confidence_floor 
[gw3] [ 21%] PASSED tests/test_consolidation_prompt.py::test_no_hard_confidence_floor 
[gw2] [ 22%] PASSED tests/test_consolidator_core.py::test_parse_json_variants 
tests/test_consolidator_core.py::test_fetch_next_messages_and_senders 
[gw1] [ 22%] PASSED tests/test_compressor.py::test_maybe_compress_light_runs_once 
tests/test_consolidator_core.py::test_checkpoint_and_state_table 
tests/test_consolidator_core.py::test_normalize_user_id 
[gw1] [ 23%] PASSED tests/test_consolidator_core.py::test_normalize_user_id 
tests/test_consolidator_core.py::test_write_short_term_upsert 
[gw0] [ 23%] PASSED tests/test_compressor.py::test_maybe_compress_skips_when_cooled_down 
tests/test_consolidator_core.py::test_merge_traits_dedupes 
[gw0] [ 24%] PASSED tests/test_consolidator_core.py::test_merge_traits_dedupes 
tests/test_consolidator_core.py::test_write_memory_candidates_whitelist 
[gw3] [ 24%] PASSED tests/test_consolidator_core.py::test_checkpoint_and_state_table 
tests/test_consolidator_core.py::test_count_new_messages_and_has_new 
[gw2] [ 25%] PASSED tests/test_consolidator_core.py::test_fetch_next_messages_and_senders 
tests/test_consolidator_core.py::test_fetch_next_messages_source_kind_at_mention 
[gw1] [ 25%] PASSED tests/test_consolidator_core.py::test_write_short_term_upsert 
tests/test_consolidator_core.py::test_write_user_profiles_new_and_merge 
[gw3] [ 26%] PASSED tests/test_consolidator_core.py::test_count_new_messages_and_has_new 
tests/test_consolidator_core.py::test_build_prompt_and_fetch_summary 
[gw0] [ 26%] PASSED tests/test_consolidator_core.py::test_write_memory_candidates_whitelist 
[gw2] [ 26%] PASSED tests/test_consolidator_core.py::test_fetch_next_messages_source_kind_at_mention 
tests/test_consolidator_core.py::test_write_long_term_memories 
tests/test_context_tail.py::test_summary_and_tail_coexist 
[gw2] [ 27%] PASSED tests/test_context_tail.py::test_summary_and_tail_coexist 
tests/test_context_tail.py::test_bot_question_precedes_user_reply 
[gw2] [ 27%] PASSED tests/test_context_tail.py::test_bot_question_precedes_user_reply 
tests/test_cross_user_isolation.py::test_candidate_promotion_does_not_merge_across_users 
[gw0] [ 28%] PASSED tests/test_consolidator_core.py::test_write_long_term_memories 
tests/test_context_tail.py::test_tail_in_time_order 
[gw2] [ 28%] PASSED tests/test_cross_user_isolation.py::test_candidate_promotion_does_not_merge_across_users 
tests/test_cross_user_isolation.py::test_compressor_does_not_merge_across_users 
[gw0] [ 29%] PASSED tests/test_context_tail.py::test_tail_in_time_order 
tests/test_cross_user_isolation.py::test_compressor_still_merges_same_user 
[gw2] [ 29%] PASSED tests/test_cross_user_isolation.py::test_compressor_does_not_merge_across_users 
[gw1] [ 30%] PASSED tests/test_consolidator_core.py::test_write_user_profiles_new_and_merge 
tests/test_cross_user_isolation.py::test_retrieval_merge_similar_keeps_users_separate 
[gw2] [ 30%] PASSED tests/test_cross_user_isolation.py::test_retrieval_merge_similar_keeps_users_separate 
tests/test_context_tail.py::test_no_tail_falls_back_to_exchanges 
tests/test_db_cleaner.py::test_clean_db_clears_tables_and_resets_seq 
[gw3] [ 31%] PASSED tests/test_consolidator_core.py::test_build_prompt_and_fetch_summary 
[gw0] [ 31%] PASSED tests/test_cross_user_isolation.py::test_compressor_still_merges_same_user 
tests/test_cross_user_isolation.py::test_retrieval_merge_similar_still_merges_same_user 
tests/test_context_tail.py::test_bot_self_rendered_as_wo 
[gw0] [ 31%] PASSED tests/test_cross_user_isolation.py::test_retrieval_merge_similar_still_merges_same_user 
tests/test_db_cleaner.py::test_needs_cleanup_logic 
[gw1] [ 32%] PASSED tests/test_context_tail.py::test_no_tail_falls_back_to_exchanges 
[gw0] [ 32%] PASSED tests/test_db_cleaner.py::test_needs_cleanup_logic 
tests/test_db_cleaner.py::test_clean_db_missing_file 
tests/test_db_cleaner.py::test_print_summary_runs 
[gw1] [ 33%] PASSED tests/test_db_cleaner.py::test_clean_db_missing_file 
tests/test_db_cleaner.py::test_mark_cleanup_done_handles_error 
[gw3] [ 33%] PASSED tests/test_context_tail.py::test_bot_self_rendered_as_wo 
tests/test_db_cleaner.py::test_trim_group_messages_missing_db 
[gw1] [ 34%] PASSED tests/test_db_cleaner.py::test_mark_cleanup_done_handles_error 
tests/test_embeddings.py::test_cosine_mismatched_dim_returns_zero 
[gw2] [ 34%] PASSED tests/test_db_cleaner.py::test_clean_db_clears_tables_and_resets_seq 
[gw3] [ 35%] PASSED tests/test_db_cleaner.py::test_trim_group_messages_missing_db 
[gw1] [ 35%] PASSED tests/test_embeddings.py::test_cosine_mismatched_dim_returns_zero 
tests/test_db_cleaner.py::test_trim_group_messages_keeps_recent 
tests/test_embeddings.py::test_embedding_service_caches_and_calls 
tests/test_embeddings.py::test_embedding_service_degrades_on_failure 
[gw0] [ 36%] PASSED tests/test_db_cleaner.py::test_print_summary_runs 
tests/test_embeddings.py::test_normalize_and_cosine 
[gw0] [ 36%] PASSED tests/test_embeddings.py::test_normalize_and_cosine 
tests/test_embeddings.py::test_retrieve_memories_emb_falls_back_on_service_failure 
[gw2] [ 36%] PASSED tests/test_db_cleaner.py::test_trim_group_messages_keeps_recent 
tests/test_embeddings.py::test_embedding_service_empty_text 
[gw0] [ 37%] PASSED tests/test_embeddings.py::test_retrieve_memories_emb_falls_back_on_service_failure 
[gw2] [ 37%] PASSED tests/test_embeddings.py::test_embedding_service_empty_text 
tests/test_full_workflow.py::test_full_workflow_chat_message_to_reply 
tests/test_full_workflow.py::test_full_workflow_consolidation_promotes_memory 
[gw0] [ 38%] PASSED tests/test_full_workflow.py::test_full_workflow_chat_message_to_reply 
tests/test_full_workflow.py::test_full_workflow_summary_feeds_next_reply 
[gw3] [ 38%] PASSED tests/test_embeddings.py::test_embedding_service_caches_and_calls 
tests/test_embeddings.py::test_rank_memories_uses_injected_semantic_scores 
[gw3] [ 39%] PASSED tests/test_embeddings.py::test_rank_memories_uses_injected_semantic_scores 
[gw2] [ 39%] PASSED tests/test_full_workflow.py::test_full_workflow_consolidation_promotes_memory 
tests/test_full_workflow.py::test_full_workflow_force_consolidation_small_batch 
tests/test_lm_studio.py::test_generate_success_path 
[gw3] [ 40%] PASSED tests/test_lm_studio.py::test_generate_success_path 
tests/test_lm_studio.py::test_generate_retries_on_empty_reply 
[gw3] [ 40%] PASSED tests/test_lm_studio.py::test_generate_retries_on_empty_reply 
tests/test_lm_studio.py::test_generate_exhausts_retries_on_generic_error 
[gw0] [ 41%] PASSED tests/test_full_workflow.py::test_full_workflow_summary_feeds_next_reply 
tests/test_lm_studio.py::test_constructor_normalizes_url 
[gw0] [ 41%] PASSED tests/test_lm_studio.py::test_constructor_normalizes_url 
tests/test_memory_manager.py::test_high_value_candidate_becomes_confirmed_memory 
[gw1] [ 42%] PASSED tests/test_embeddings.py::test_embedding_service_degrades_on_failure 
[gw2] [ 42%] PASSED tests/test_full_workflow.py::test_full_workflow_force_consolidation_small_batch 
tests/test_embeddings.py::test_retrieve_memories_emb_routes_semantic_scores 
tests/test_lm_studio.py::test_generate_gives_up_on_4xx 
[gw2] [ 42%] PASSED tests/test_lm_studio.py::test_generate_gives_up_on_4xx 
tests/test_memory_manager_fts_sync.py::test_fts_disabled_means_no_index_and_query_falls_back 
[gw1] [ 43%] PASSED tests/test_embeddings.py::test_retrieve_memories_emb_routes_semantic_scores 
tests/test_memory_manager_fts_sync.py::test_fts_index_sync_after_merge_updates_content 
[gw0] [ 43%] PASSED tests/test_memory_manager.py::test_high_value_candidate_becomes_confirmed_memory 
tests/test_memory_manager_fts_sync.py::test_fts_index_stays_in_sync_after_promotion 
[gw2] [ 44%] PASSED tests/test_memory_manager_fts_sync.py::test_fts_disabled_means_no_index_and_query_falls_back 
tests/test_memory_manager_fts_sync.py::test_fts_rebuilds_when_index_is_stale 
[gw1] [ 44%] PASSED tests/test_memory_manager_fts_sync.py::test_fts_index_sync_after_merge_updates_content 
tests/test_memory_manager_v2.py::test_detect_contradiction 
[gw1] [ 45%] PASSED tests/test_memory_manager_v2.py::test_detect_contradiction 
tests/test_pipeline_compose.py::test_normal_reply_context_before_message 
[gw0] [ 45%] PASSED tests/test_memory_manager_fts_sync.py::test_fts_index_stays_in_sync_after_promotion 
[gw1] [ 46%] PASSED tests/test_pipeline_compose.py::test_normal_reply_context_before_message 
tests/test_memory_manager_v2.py::test_conflict_marks_old_memory 
tests/test_pipeline_compose.py::test_proactive_at_instruction_before_context 
[gw1] [ 46%] PASSED tests/test_pipeline_compose.py::test_proactive_at_instruction_before_context 
tests/test_pipeline_compose.py::test_normal_no_context_returns_message 
[gw1] [ 47%] PASSED tests/test_pipeline_compose.py::test_normal_no_context_returns_message 
tests/test_policy.py::test_usage_blocked_when_not_in_mode 
[gw1] [ 47%] PASSED tests/test_policy.py::test_usage_blocked_when_not_in_mode 
[gw2] [ 47%] PASSED tests/test_memory_manager_fts_sync.py::test_fts_rebuilds_when_index_is_stale 
tests/test_policy.py::test_usage_allowed_when_in_mode 
tests/test_memory_manager_v2.py::test_candidate_meta_fields_persisted 
[gw1] [ 48%] PASSED tests/test_policy.py::test_usage_allowed_when_in_mode 
tests/test_policy.py::test_boundary_never_chat_material_in_casual 
[gw1] [ 48%] PASSED tests/test_policy.py::test_boundary_never_chat_material_in_casual 
tests/test_policy.py::test_visibility_restricted_allowed_in_conflict 
[gw1] [ 49%] PASSED tests/test_policy.py::test_visibility_restricted_allowed_in_conflict 
tests/test_policy.py::test_detect_mode_tech_and_recommend 
[gw1] [ 49%] PASSED tests/test_policy.py::test_detect_mode_tech_and_recommend 
tests/test_policy.py::test_detect_mode_proactive 
[gw1] [ 50%] PASSED tests/test_policy.py::test_detect_mode_proactive 
tests/test_policy.py::test_detect_mode_echo_noise_stays_casual 
[gw1] [ 50%] PASSED tests/test_policy.py::test_detect_mode_echo_noise_stays_casual 
tests/test_policy.py::test_detect_mode_ignore_daily_grumbling_conflict 
[gw1] [ 51%] PASSED tests/test_policy.py::test_detect_mode_ignore_daily_grumbling_conflict 
[gw0] [ 51%] PASSED tests/test_memory_manager_v2.py::test_conflict_marks_old_memory 
tests/test_pipeline_compose.py::test_proactive_at_no_context_returns_instruction 
[gw0] [ 52%] PASSED tests/test_pipeline_compose.py::test_proactive_at_no_context_returns_instruction 
tests/test_policy.py::test_detect_mode_scoring_beats_priority_chain 
tests/test_policy.py::test_rank_contextual_blocked_when_unrelated 
[gw1] [ 52%] PASSED tests/test_policy.py::test_detect_mode_scoring_beats_priority_chain 
[gw2] [ 52%] PASSED tests/test_memory_manager_v2.py::test_candidate_meta_fields_persisted 
[gw0] [ 53%] PASSED tests/test_policy.py::test_rank_contextual_blocked_when_unrelated 
tests/test_policy.py::test_rank_contextual_exempted_by_strong_usage 
tests/test_policy.py::test_rank_contextual_exempted_by_trigger_topic 
tests/test_policy.py::test_visibility_restricted_denied_in_casual 
[gw1] [ 53%] PASSED tests/test_policy.py::test_rank_contextual_exempted_by_strong_usage 
[gw2] [ 54%] PASSED tests/test_policy.py::test_visibility_restricted_denied_in_casual 
[gw0] [ 54%] PASSED tests/test_policy.py::test_rank_contextual_exempted_by_trigger_topic 
tests/test_policy.py::test_rank_memories_attaches_score 
tests/test_policy.py::test_rank_places_mode_matched_higher 
[gw2] [ 55%] PASSED tests/test_policy.py::test_rank_memories_attaches_score 
tests/test_policy.py::test_trigger_topic_match_keywords_and_topics 
[gw0] [ 55%] PASSED tests/test_policy.py::test_rank_places_mode_matched_higher 
tests/test_policy.py::test_split_behavior_constraints 
[gw1] [ 56%] PASSED tests/test_policy.py::test_trigger_topic_match_keywords_and_topics 
tests/test_policy.py::test_stable_profile_facts_filters_persona 
[gw2] [ 56%] PASSED tests/test_policy.py::test_split_behavior_constraints 
tests/test_policy.py::test_validate_candidate_corrects_boundary_mislabel 
[gw0] [ 57%] PASSED tests/test_policy.py::test_stable_profile_facts_filters_persona 
tests/test_proactive_at_flow.py::test_record_at_counts_and_persists 
[gw1] [ 57%] PASSED tests/test_policy.py::test_validate_candidate_corrects_boundary_mislabel 
tests/test_proactive_at_flow.py::test_no_reply_accumulates_then_resets 
tests/test_proactive_at_flow.py::test_quota_is_per_user 
[gw2] [ 57%] PASSED tests/test_proactive_at_flow.py::test_record_at_counts_and_persists 
tests/test_proactive_at_flow.py::test_last_spoke_ts_detects_reply 
[gw2] [ 58%] PASSED tests/test_proactive_at_flow.py::test_last_spoke_ts_detects_reply 
tests/test_proactive_prompt.py::test_common_rules_present_in_both 
[gw1] [ 58%] PASSED tests/test_proactive_at_flow.py::test_quota_is_per_user 
[gw2] [ 59%] PASSED tests/test_proactive_prompt.py::test_common_rules_present_in_both 
[gw0] [ 59%] PASSED tests/test_proactive_at_flow.py::test_no_reply_accumulates_then_resets 
tests/test_proactive_prompt.py::test_no_placeholder_left 
tests/test_proactive_prompt.py::test_coldstart_instruction_contains_topic 
[gw2] [ 60%] PASSED tests/test_proactive_prompt.py::test_no_placeholder_left 
[gw1] [ 60%] PASSED tests/test_proactive_prompt.py::test_coldstart_instruction_contains_topic 
tests/test_proactive_prompt.py::test_verify_instruction_contains_content_and_rules 
[gw0] [ 61%] PASSED tests/test_proactive_prompt.py::test_verify_instruction_contains_content_and_rules 
tests/test_proactive_prompt.py::test_context_role_clause_present 
[gw1] [ 61%] PASSED tests/test_proactive_prompt.py::test_context_role_clause_present 
tests/test_proactive_rules.py::test_silent_group_never_speaks 
tests/test_proactive_prompt.py::test_build_instruction_dispatches_by_mode 
[gw0] [ 62%] PASSED tests/test_proactive_rules.py::test_silent_group_never_speaks 
tests/test_proactive_rules.py::test_too_low_frequency_never_speaks 
tests/test_proactive_rules.py::test_previous_logic_still_respects_cooldown 
[gw2] [ 62%] PASSED tests/test_proactive_prompt.py::test_build_instruction_dispatches_by_mode 
[gw1] [ 63%] PASSED tests/test_proactive_rules.py::test_too_low_frequency_never_speaks 
[gw0] [ 63%] PASSED tests/test_proactive_rules.py::test_previous_logic_still_respects_cooldown 
tests/test_proactive_rules.py::test_group_interval_aggregated_across_users 
tests/test_proactive_rules.py::test_recently_spoken_dedup 
[gw2] [ 63%] PASSED tests/test_proactive_rules.py::test_recently_spoken_dedup 
tests/test_proactive_rules.py::test_ngrams_is_reasonable 
[gw1] [ 64%] PASSED tests/test_proactive_rules.py::test_ngrams_is_reasonable 
[gw0] [ 64%] PASSED tests/test_proactive_rules.py::test_group_interval_aggregated_across_users 
tests/test_proactive_rules.py::test_active_users_filters_window_and_sorts_desc 
tests/test_proactive_rules.py::test_user_average_interval_requires_two 
[gw2] [ 65%] PASSED tests/test_proactive_rules.py::test_active_users_filters_window_and_sorts_desc 
tests/test_proactive_rules.py::test_curve_at_fast_anchor 
[gw0] [ 65%] PASSED tests/test_proactive_rules.py::test_curve_at_fast_anchor 
tests/test_proactive_rules.py::test_curve_at_slow_anchor 
tests/test_proactive_rules.py::test_curve_gamma_2_lower_than_gamma_1 
[gw2] [ 66%] PASSED tests/test_proactive_rules.py::test_curve_at_slow_anchor 
[gw1] [ 66%] PASSED tests/test_proactive_rules.py::test_user_average_interval_requires_two 
[gw0] [ 67%] PASSED tests/test_proactive_rules.py::test_curve_gamma_2_lower_than_gamma_1 
tests/test_proactive_rules.py::test_curve_bad_anchor_no_error 
tests/test_proactive_rules.py::test_curve_midpoint_between_anchors 
[gw2] [ 67%] PASSED tests/test_proactive_rules.py::test_curve_bad_anchor_no_error 
tests/test_proactive_state.py::test_at_count_increments 
tests/test_proactive_state.py::test_cross_day_resets_count 
[gw1] [ 68%] PASSED tests/test_proactive_rules.py::test_curve_midpoint_between_anchors 
tests/test_proactive_state.py::test_consecutive_no_reply_increment_and_reset 
[gw2] [ 68%] PASSED tests/test_proactive_state.py::test_cross_day_resets_count 
[gw0] [ 68%] PASSED tests/test_proactive_state.py::test_at_count_increments 
tests/test_proactive_state.py::test_missing_table_returns_defaults_without_error 
tests/test_proactive_state.py::test_count_user_messages_24h_excludes_bot_self 
[gw1] [ 69%] PASSED tests/test_proactive_state.py::test_consecutive_no_reply_increment_and_reset 
[gw2] [ 69%] PASSED tests/test_proactive_state.py::test_missing_table_returns_defaults_without_error 
tests/test_proactive_target.py::test_at_quota_interpolation 
[gw0] [ 70%] PASSED tests/test_proactive_state.py::test_count_user_messages_24h_excludes_bot_self 
tests/test_proactive_target.py::test_at_quota_bad_bounds_no_error 
[gw1] [ 70%] PASSED tests/test_proactive_target.py::test_at_quota_interpolation 
[gw2] [ 71%] PASSED tests/test_proactive_target.py::test_at_quota_bad_bounds_no_error 
tests/test_proactive_target.py::test_cooldown_elapsed_variants 
tests/test_proactive_target.py::test_can_at_user_quota_with_record_at_flow 
tests/test_proactive_target.py::test_can_at_user_quota_full 
[gw0] [ 71%] PASSED tests/test_proactive_target.py::test_cooldown_elapsed_variants 
tests/test_proactive_target.py::test_can_at_user_no_reply_backoff 
[gw1] [ 72%] PASSED tests/test_proactive_target.py::test_can_at_user_quota_full 
[gw2] [ 72%] PASSED tests/test_proactive_target.py::test_can_at_user_quota_with_record_at_flow 
tests/test_proactive_target.py::test_can_at_user_disabled 
tests/test_proactive_target.py::test_pick_target_no_active_users 
[gw1] [ 73%] PASSED tests/test_proactive_target.py::test_can_at_user_disabled 
[gw0] [ 73%] PASSED tests/test_proactive_target.py::test_can_at_user_no_reply_backoff 
[gw2] [ 73%] PASSED tests/test_proactive_target.py::test_pick_target_no_active_users 
tests/test_proactive_target.py::test_pick_target_verify_mode 
tests/test_proactive_target.py::test_pick_target_verify_prefers_highest_confidence 
tests/test_proactive_target.py::test_pick_target_coldstart_avoids_last_topic 
[gw1] [ 74%] PASSED tests/test_proactive_target.py::test_pick_target_verify_prefers_highest_confidence 
[gw0] [ 74%] PASSED tests/test_proactive_target.py::test_pick_target_verify_mode 
tests/test_proactive_target.py::test_pick_target_exclude_user_ids 
tests/test_proactive_target.py::test_fetch_observing_candidate_window 
[gw1] [ 75%] PASSED tests/test_proactive_target.py::test_pick_target_exclude_user_ids 
[gw0] [ 75%] PASSED tests/test_proactive_target.py::test_fetch_observing_candidate_window 
tests/test_prompt_builder_v2.py::test_build_v2_prompt_context_partitions_sections 
[gw0] [ 76%] PASSED tests/test_prompt_builder_v2.py::test_build_v2_prompt_context_partitions_sections 
tests/test_proactive_target.py::test_target_nickname_default 
[gw1] [ 76%] PASSED tests/test_proactive_target.py::test_target_nickname_default 
tests/test_prompt_builder_v2.py::test_build_v2_prompt_context_omits_empty_sections 
[gw0] [ 77%] PASSED tests/test_prompt_builder_v2.py::test_build_v2_prompt_context_omits_empty_sections 
tests/test_prompt_builder_v2.py::test_tech_mode_has_larger_conversation_budget 
tests/test_prompt_builder_v2.py::test_trace_records_and_statistics 
[gw1] [ 77%] PASSED tests/test_prompt_builder_v2.py::test_tech_mode_has_larger_conversation_budget 
tests/test_rag_switches.py::test_rag_disabled_uses_weighted_fallback_ranking 
[gw0] [ 78%] PASSED tests/test_prompt_builder_v2.py::test_trace_records_and_statistics 
tests/test_rag_switches.py::test_fts_disabled_minnes_total_also_digit_ranking 
[gw1] [ 78%] PASSED tests/test_rag_switches.py::test_rag_disabled_uses_weighted_fallback_ranking 
[gw0] [ 78%] PASSED tests/test_rag_switches.py::test_fts_disabled_minnes_total_also_digit_ranking 
tests/test_rag_switches.py::test_get_user_memories_query_scopes_to_user 
tests/test_rag_switches.py::test_rag_disabled_does_not_create_fts_table 
[gw2] [ 79%] FAILED tests/test_proactive_target.py::test_pick_target_coldstart_avoids_last_topic 
tests/test_proactive_target.py::test_topic_covered_variants 
[gw2] [ 79%] PASSED tests/test_proactive_target.py::test_topic_covered_variants 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_conflict_mode_activates_behavior_guard 
[gw0] [ 80%] PASSED tests/test_rag_switches.py::test_rag_disabled_does_not_create_fts_table 
[gw1] [ 80%] PASSED tests/test_rag_switches.py::test_get_user_memories_query_scopes_to_user 
tests/test_rag_switches.py::test_rag_top_k_sets_candidate_pool_floor 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_filters_restricted_in_casual 
[gw2] [ 81%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_conflict_mode_activates_behavior_guard 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_proactive_uses_group_memories 
[gw0] [ 81%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_filters_restricted_in_casual 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_score_floor_filters_noise 
[gw1] [ 82%] PASSED tests/test_rag_switches.py::test_rag_top_k_sets_candidate_pool_floor 
[gw2] [ 82%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_proactive_uses_group_memories 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_fts_path_returns_qualified_columns 
tests/test_retrieval_v2_and_schema.py::test_schema_migration_adds_columns 
[gw0] [ 83%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_score_floor_filters_noise 
tests/test_retrieval_v2_and_schema.py::test_schema_migration_does_not_touch_existing_data 
[gw1] [ 83%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_fts_path_returns_qualified_columns 
tests/test_retriever.py::test_related_memories_are_ranked_by_relevance_and_recency 
[gw1] [ 84%] PASSED tests/test_retriever.py::test_related_memories_are_ranked_by_relevance_and_recency 
[gw0] [ 84%] PASSED tests/test_retrieval_v2_and_schema.py::test_schema_migration_does_not_touch_existing_data 
tests/test_retriever.py::test_group_memories_query_prefers_rag_results 
tests/test_retriever.py::test_group_memories_prefer_recent_and_important_entries 
[gw2] [ 84%] PASSED tests/test_retrieval_v2_and_schema.py::test_schema_migration_adds_columns 
tests/test_retriever.py::test_related_memories_use_sqlite_rag_index 
[gw0] [ 85%] PASSED tests/test_retriever.py::test_group_memories_prefer_recent_and_important_entries 
tests/test_short_term_attribution.py::test_write_and_read_short_term_keeps_attribution 
[gw1] [ 85%] PASSED tests/test_retriever.py::test_group_memories_query_prefers_rag_results 
tests/test_retriever.py::test_user_memories_query_prefers_rag_results 
[gw2] [ 86%] PASSED tests/test_retriever.py::test_related_memories_use_sqlite_rag_index 
tests/test_short_term_attribution.py::test_build_context_falls_back_when_column_missing 
[gw1] [ 86%] PASSED tests/test_retriever.py::test_user_memories_query_prefers_rag_results 
[gw2] [ 87%] PASSED tests/test_short_term_attribution.py::test_build_context_falls_back_when_column_missing 
tests/test_short_term_attribution.py::test_memory_candidates_drop_unknown_sender 
tests/test_short_term_attribution.py::test_prompt_builder_attributes_current_user 
[gw2] [ 87%] PASSED tests/test_short_term_attribution.py::test_prompt_builder_attributes_current_user 
tests/test_source_kind.py::test_passive_messages_get_no_marker 
[gw2] [ 88%] PASSED tests/test_source_kind.py::test_passive_messages_get_no_marker 
tests/test_source_kind.py::test_at_mention_messages_get_marker 
[gw2] [ 88%] PASSED tests/test_source_kind.py::test_at_mention_messages_get_marker 
[gw0] [ 89%] PASSED tests/test_short_term_attribution.py::test_write_and_read_short_term_keeps_attribution 
tests/test_text_similarity.py::test_normalize_text_strips_punctuation_and_case 
tests/test_short_term_attribution.py::test_fetch_current_summary_includes_exchanges 
[gw2] [ 89%] PASSED tests/test_text_similarity.py::test_normalize_text_strips_punctuation_and_case 
tests/test_text_similarity.py::test_jaccard_edges 
[gw2] [ 89%] PASSED tests/test_text_similarity.py::test_jaccard_edges 
tests/test_text_similarity.py::test_is_similar_rejects_unrelated 
[gw2] [ 90%] PASSED tests/test_text_similarity.py::test_is_similar_rejects_unrelated 
tests/test_text_similarity.py::test_is_similar_empty_is_never_similar 
[gw2] [ 90%] PASSED tests/test_text_similarity.py::test_is_similar_empty_is_never_similar 
tests/test_text_similarity.py::test_is_similar_threshold_is_configurable 
[gw2] [ 91%] PASSED tests/test_text_similarity.py::test_is_similar_threshold_is_configurable 
tests/test_text_similarity.py::test_merge_content_prefers_more_complete 
[gw2] [ 91%] PASSED tests/test_text_similarity.py::test_merge_content_prefers_more_complete 
[gw1] [ 92%] PASSED tests/test_short_term_attribution.py::test_memory_candidates_drop_unknown_sender 
tests/test_short_term_attribution.py::test_consolidate_group_unpacks_senders 
tests/test_text_similarity.py::test_merge_content_joins_distinct 
[gw2] [ 92%] PASSED tests/test_text_similarity.py::test_merge_content_joins_distinct 
tests/test_trace.py::test_record_trace_disabled 
[gw2] [ 93%] PASSED tests/test_trace.py::test_record_trace_disabled 
tests/test_trace.py::test_record_trace_creates_table_and_inserts 
[gw2] [ 93%] PASSED tests/test_trace.py::test_record_trace_creates_table_and_inserts 
[gw0] [ 94%] PASSED tests/test_short_term_attribution.py::test_fetch_current_summary_includes_exchanges 
tests/test_trace.py::test_record_trace_truncates_long_fields 
tests/test_text_similarity.py::test_is_similar_identical_and_substring 
[gw0] [ 94%] PASSED tests/test_text_similarity.py::test_is_similar_identical_and_substring 
tests/test_trace.py::test_dump_and_parse_helpers 
[gw2] [ 94%] PASSED tests/test_trace.py::test_record_trace_truncates_long_fields 
[gw0] [ 95%] PASSED tests/test_trace.py::test_dump_and_parse_helpers 
tests/test_trace.py::test_record_trace_no_memory_fields 
tests/test_trace.py::test_memory_statistics 
[gw2] [ 95%] PASSED tests/test_trace.py::test_record_trace_no_memory_fields 
tests/test_trace.py::test_memory_statistics_empty_and_missing_db 
[gw0] [ 96%] PASSED tests/test_trace.py::test_memory_statistics 
[gw2] [ 96%] PASSED tests/test_trace.py::test_memory_statistics_empty_and_missing_db 
tests/test_trace.py::test_prune_traces 
tests/test_trace.py::test_prune_traces_no_db 
[gw2] [ 97%] PASSED tests/test_trace.py::test_prune_traces_no_db 
[gw0] [ 97%] PASSED tests/test_trace.py::test_prune_traces 
tests/test_trace.py::test_statistics_on_broken_rows 
[gw1] [ 98%] PASSED tests/test_short_term_attribution.py::test_consolidate_group_unpacks_senders 
tests/test_text_similarity.py::test_merge_content_handles_empty 
[gw0] [ 98%] PASSED tests/test_trace.py::test_statistics_on_broken_rows 
[gw1] [ 99%] PASSED tests/test_text_similarity.py::test_merge_content_handles_empty 
[gw3] [ 99%] PASSED tests/test_lm_studio.py::test_generate_exhausts_retries_on_generic_error 
tests/test_memory_manager.py::test_low_value_candidate_goes_to_observing 
[gw3] [100%] PASSED tests/test_memory_manager.py::test_low_value_candidate_goes_to_observing 

==================================== ERRORS ====================================
___________________ ERROR collecting tests/test_benchmark.py ___________________
ImportError while importing test module '/home/runner/work/Stella_project/Stella_project/tests/test_benchmark.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/hostedtoolcache/Python/3.10.20/x64/lib/python3.10/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/test_benchmark.py:9: in <module>
    import numpy as np
E   ModuleNotFoundError: No module named 'numpy'
=================================== FAILURES ===================================
_________________ test_pick_target_coldstart_avoids_last_topic _________________
[gw2] linux -- Python 3.10.20 /opt/hostedtoolcache/Python/3.10.20/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_pick_target_coldstart_avo0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f4729102dd0>

    def test_pick_target_coldstart_avoids_last_topic(tmp_path, monkeypatch):
        """无候选 → mode=coldstart，且 topic 不等于 last_asked_topic。"""
        _setup_db(monkeypatch, tmp_path)
        monkeypatch.setattr(pt, "PROACTIVE_COLDSTART_TOPICS", ["游戏话题", "美食话题"])
        monkeypatch.setattr(proactive.time, "monotonic", _faketicks())
        c = proactive.ProactiveController()
        monkeypatch.setattr(pt, "get_proactive", lambda: c)
        c.record_message(1, 2001)
        proactive_state.record_at(1, 2001, topic="游戏话题")
    
        target = pick_target(1)
>       assert target is not None
E       assert None is not None

tests/test_proactive_target.py:225: AssertionError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.20-final-0 _______________

Name                                    Stmts   Miss Branch BrPart  Cover
-------------------------------------------------------------------------
config/__init__.py                          1      0      0      0   100%
config/settings.py                        179     15     18      7    89%
core/__init__.py                            0      0      0      0   100%
core/context.py                            27      0      0      0   100%
core/llm/__init__.py                        3      0      0      0   100%
core/llm/base.py                            5      0      0      0   100%
core/llm/lm_studio.py                      54      3     14      3    91%
core/pipeline.py                           81     19     18      6    75%
memory/__init__.py                          0      0      0      0   100%
memory/benchmark.py                       250    111     70      5    51%
memory/compressor.py                      154     10     38      7    90%
memory/consolidation_log.py                11      0      2      0   100%
memory/consolidation_prompt.py              6      0      0      0   100%
memory/consolidator.py                    424     70    144     25    82%
memory/db_cleaner.py                       98     20     32      6    78%
memory/embeddings.py                       65      5     16      4    89%
memory/memory_manager.py                  229     14     72     10    91%
memory/policy.py                          316     39    124     15    85%
memory/post_processors.py                  61     10     20      9    74%
memory/pre_processors.py                  196     75     72     18    56%
memory/proactive.py                       106     12     28      6    85%
memory/proactive_prompt.py                 12      0      2      0   100%
memory/proactive_state.py                  52      7      4      0    88%
memory/proactive_target.py                109     21     38      5    81%
memory/prompt_builder.py                  105     36     54     11    62%
memory/retrieval_v2.py                    185     31     50     12    80%
memory/retriever.py                       242     32    112     28    83%
memory/schema.py                          148     42     50      7    67%
memory/text_similarity.py                  33      1     16      1    96%
memory/trace.py                            89     11     20      1    89%
tests/conftest.py                          10      0      0      0   100%
tests/test_benchmark.py                    63     60     16      0     4%
tests/test_benchmark_and_log.py            71      1      0      0    99%
tests/test_bot_self_source.py              64      0      0      0   100%
tests/test_candidate_reinforcement.py     176      0      8      0   100%
tests/test_compressor.py                  110      1      0      0    99%
tests/test_consolidation_prompt.py         26      0      2      0   100%
tests/test_consolidator_core.py           163      0      0      0   100%
tests/test_context_tail.py                 58      2      2      0    97%
tests/test_cross_user_isolation.py         61      0      0      0   100%
tests/test_db_cleaner.py                   77      0      2      0   100%
tests/test_embeddings.py                   99      3      8      2    95%
tests/test_full_workflow.py               147      0      2      0   100%
tests/test_lm_studio.py                    77      1      2      0    99%
tests/test_memory_manager.py               51      0      0      0   100%
tests/test_memory_manager_fts_sync.py      66      0      0      0   100%
tests/test_memory_manager_v2.py            54      0      0      0   100%
tests/test_pipeline_compose.py             17      0      0      0   100%
tests/test_policy.py                       80      0      0      0   100%
tests/test_proactive_at_flow.py            41      0      0      0   100%
tests/test_proactive_prompt.py             34      0      8      0   100%
tests/test_proactive_rules.py             124      0      0      0   100%
tests/test_proactive_state.py              46      0      0      0   100%
tests/test_proactive_target.py            158      3      6      0    98%
tests/test_prompt_builder_v2.py            38      0      0      0   100%
tests/test_rag_switches.py                 68      0      0      0   100%
tests/test_retrieval_v2_and_schema.py     124      0      2      0   100%
tests/test_retriever.py                    78      0      0      0   100%
tests/test_short_term_attribution.py      107      0      0      0   100%
tests/test_source_kind.py                  25      0      0      0   100%
tests/test_text_similarity.py              32      0      0      0   100%
tests/test_trace.py                        99      0      0      0   100%
-------------------------------------------------------------------------
TOTAL                                    5685    655   1072    188    85%
=========================== short test summary info ============================
FAILED tests/test_proactive_target.py::test_pick_target_coldstart_avoids_last_topic - assert None is not None
ERROR tests/test_benchmark.py - ImportError while importing test module '/home/runner/work/Stella_project/Stella_project/tests/test_benchmark.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/hostedtoolcache/Python/3.10.20/x64/lib/python3.10/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/test_benchmark.py:9: in <module>
    import numpy as np
E   ModuleNotFoundError: No module named 'numpy'
==================== 1 failed, 218 passed, 1 error in 7.64s ====================
Error: Process completed with exit code 1.

# test (3.11)

Run pytest tests/ \
  pytest tests/ \
    -v \
    --cov=. \
    --cov-branch \
    -n auto \
    --dist loadgroup
  shell: /usr/bin/bash -e {0}
  env:
    pythonLocation: /opt/hostedtoolcache/Python/3.11.15/x64
    PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.11.15/x64/lib/pkgconfig
    Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.15/x64
    Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.15/x64
    Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.15/x64
    LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.11.15/x64/lib
    COVERAGE_FILE: cov-3.11
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0 -- /opt/hostedtoolcache/Python/3.11.15/x64/bin/python
cachedir: .pytest_cache
rootdir: /home/runner/work/Stella_project/Stella_project
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2, xdist-3.8.0
created: 4/4 workers
4 workers [219 items]

scheduling tests via LoadGroupScheduling

tests/test_benchmark_and_log.py::test_load_cases_missing_dir 
tests/test_benchmark_and_log.py::test_load_cases_list_and_broken 
tests/test_benchmark_and_log.py::test_evaluate_case_basic 
tests/test_benchmark_and_log.py::test_evaluate_case_forbidden_reported 
[gw1] [  0%] PASSED tests/test_benchmark_and_log.py::test_load_cases_list_and_broken 
[gw0] [  0%] PASSED tests/test_benchmark_and_log.py::test_load_cases_missing_dir 
tests/test_benchmark_and_log.py::test_run_benchmark_empty_dir 
tests/test_benchmark_and_log.py::test_evaluate_case_expected_in_behavior_constraints 
[gw1] [  1%] PASSED tests/test_benchmark_and_log.py::test_run_benchmark_empty_dir 
tests/test_benchmark_and_log.py::test_consolidation_log_append_and_create 
[gw1] [  1%] PASSED tests/test_benchmark_and_log.py::test_consolidation_log_append_and_create 
tests/test_bot_self_source.py::test_record_message_persists_bot_self 
[gw1] [  2%] PASSED tests/test_bot_self_source.py::test_record_message_persists_bot_self 
tests/test_bot_self_source.py::test_fetch_next_messages_bot_self_marked_and_excluded 
[gw0] [  2%] PASSED tests/test_benchmark_and_log.py::test_evaluate_case_expected_in_behavior_constraints 
[gw3] [  3%] PASSED tests/test_benchmark_and_log.py::test_evaluate_case_forbidden_reported 
[gw2] [  3%] PASSED tests/test_benchmark_and_log.py::test_evaluate_case_basic 
tests/test_benchmark_and_log.py::test_consolidation_log_handles_error 
tests/test_benchmark_and_log.py::test_evaluate_case_over_recall_respects_max_retrieved 
[gw0] [  4%] PASSED tests/test_benchmark_and_log.py::test_consolidation_log_handles_error 
tests/test_benchmark_and_log.py::test_run_benchmark_sums_metrics 
[gw1] [  4%] PASSED tests/test_bot_self_source.py::test_fetch_next_messages_bot_self_marked_and_excluded 
tests/test_bot_self_source.py::test_mixed_window_three_markers 
tests/test_bot_self_source.py::test_write_memory_candidates_drops_bot_self_candidate 
[gw1] [  5%] PASSED tests/test_bot_self_source.py::test_mixed_window_three_markers 
[gw2] [  5%] PASSED tests/test_benchmark_and_log.py::test_run_benchmark_sums_metrics 
tests/test_candidate_reinforcement.py::test_unrelated_facts_stay_separate 
tests/test_candidate_reinforcement.py::test_similar_wording_counts_as_same_fact 
[gw3] [  5%] PASSED tests/test_benchmark_and_log.py::test_evaluate_case_over_recall_respects_max_retrieved 
tests/test_candidate_reinforcement.py::test_same_fact_accumulates_instead_of_duplicating 
[gw0] [  6%] PASSED tests/test_bot_self_source.py::test_write_memory_candidates_drops_bot_self_candidate 
tests/test_candidate_reinforcement.py::test_same_content_different_users_stay_separate 
[gw2] [  6%] PASSED tests/test_candidate_reinforcement.py::test_similar_wording_counts_as_same_fact 
[gw1] [  7%] PASSED tests/test_candidate_reinforcement.py::test_unrelated_facts_stay_separate 
tests/test_candidate_reinforcement.py::test_source_kinds_accumulate_across_observations 
tests/test_candidate_reinforcement.py::test_first_seen_at_not_refreshed_on_reoccurrence 
[gw3] [  7%] PASSED tests/test_candidate_reinforcement.py::test_same_fact_accumulates_instead_of_duplicating 
tests/test_candidate_reinforcement.py::test_confidence_capped_at_one 
[gw0] [  8%] PASSED tests/test_candidate_reinforcement.py::test_same_content_different_users_stay_separate 
tests/test_candidate_reinforcement.py::test_gate1_high_confidence_promotes_immediately 
[gw0] [  8%] PASSED tests/test_candidate_reinforcement.py::test_gate1_high_confidence_promotes_immediately 
tests/test_candidate_reinforcement.py::test_gate1_low_confidence_never_promotes_even_with_at_mention 
[gw0] [  9%] PASSED tests/test_candidate_reinforcement.py::test_gate1_low_confidence_never_promotes_even_with_at_mention 
tests/test_candidate_reinforcement.py::test_gate1_importance_alone_does_not_promote 
[gw0] [  9%] PASSED tests/test_candidate_reinforcement.py::test_gate1_importance_alone_does_not_promote 
tests/test_candidate_reinforcement.py::test_gate1_trivial_importance_blocked 
[gw2] [ 10%] PASSED tests/test_candidate_reinforcement.py::test_first_seen_at_not_refreshed_on_reoccurrence 
[gw0] [ 10%] PASSED tests/test_candidate_reinforcement.py::test_gate1_trivial_importance_blocked 
[gw1] [ 10%] PASSED tests/test_candidate_reinforcement.py::test_source_kinds_accumulate_across_observations 
tests/test_candidate_reinforcement.py::test_gate1_mid_confidence_promotes_after_reoccurrence 
[gw2] [ 11%] PASSED tests/test_candidate_reinforcement.py::test_gate1_mid_confidence_promotes_after_reoccurrence 
tests/test_candidate_reinforcement.py::test_has_at_mention_tolerates_garbage 
[gw0] [ 11%] PASSED tests/test_candidate_reinforcement.py::test_has_at_mention_tolerates_garbage 
tests/test_candidate_reinforcement.py::test_reoccurrence_eventually_promotes_end_to_end 
tests/test_candidate_reinforcement.py::test_gate1_mid_confidence_passive_single_observation_waits 
tests/test_candidate_reinforcement.py::test_stale_observing_candidate_rejected 
[gw1] [ 12%] PASSED tests/test_candidate_reinforcement.py::test_gate1_mid_confidence_passive_single_observation_waits 
tests/test_candidate_reinforcement.py::test_quota_score_prefers_confirmed_and_recent 
[gw1] [ 12%] PASSED tests/test_candidate_reinforcement.py::test_quota_score_prefers_confirmed_and_recent 
tests/test_candidate_reinforcement.py::test_quota_enforce_archives_weakest 
[gw3] [ 13%] PASSED tests/test_candidate_reinforcement.py::test_confidence_capped_at_one 
tests/test_candidate_reinforcement.py::test_gate1_at_mention_promotes_single_shot 
[gw3] [ 13%] PASSED tests/test_candidate_reinforcement.py::test_gate1_at_mention_promotes_single_shot 
tests/test_compressor.py::test_weekly_no_active_memories 
[gw1] [ 14%] PASSED tests/test_candidate_reinforcement.py::test_quota_enforce_archives_weakest 
[gw0] [ 14%] PASSED tests/test_candidate_reinforcement.py::test_stale_observing_candidate_rejected 
[gw3] [ 15%] PASSED tests/test_compressor.py::test_weekly_no_active_memories 
tests/test_candidate_reinforcement.py::test_quota_score_handles_garbage 
tests/test_candidate_reinforcement.py::test_quota_is_per_user_and_per_group 
tests/test_compressor.py::test_weekly_merges_duplicates 
[gw0] [ 15%] PASSED tests/test_candidate_reinforcement.py::test_quota_score_handles_garbage 
tests/test_compressor.py::test_maybe_compress_light_runs_once 
[gw3] [ 15%] PASSED tests/test_compressor.py::test_weekly_merges_duplicates 
tests/test_compressor.py::test_maybe_compress_skips_when_cooled_down 
[gw2] [ 16%] PASSED tests/test_candidate_reinforcement.py::test_reoccurrence_eventually_promotes_end_to_end 
[gw0] [ 16%] PASSED tests/test_compressor.py::test_maybe_compress_light_runs_once 
tests/test_candidate_reinforcement.py::test_quota_dry_run_does_not_archive 
tests/test_compressor.py::test_split_into_fragments_and_store 
[gw3] [ 17%] PASSED tests/test_compressor.py::test_maybe_compress_skips_when_cooled_down 
[gw0] [ 17%] PASSED tests/test_compressor.py::test_split_into_fragments_and_store 
[gw1] [ 18%] PASSED tests/test_candidate_reinforcement.py::test_quota_is_per_user_and_per_group 
tests/test_consolidation_prompt.py::test_bot_self_clause_present 
tests/test_consolidation_prompt.py::test_no_fabrication_clauses_present 
[gw0] [ 18%] PASSED tests/test_consolidation_prompt.py::test_bot_self_clause_present 
[gw3] [ 19%] PASSED tests/test_consolidation_prompt.py::test_no_fabrication_clauses_present 
tests/test_compressor.py::test_weekly_atomizes_long_memory 
tests/test_consolidation_prompt.py::test_describes_whom_criterion_present 
[gw0] [ 19%] PASSED tests/test_consolidation_prompt.py::test_describes_whom_criterion_present 
tests/test_consolidation_prompt.py::test_empty_array_permission_present 
tests/test_consolidation_prompt.py::test_no_negative_example_blocks 
[gw3] [ 20%] PASSED tests/test_consolidation_prompt.py::test_empty_array_permission_present 
[gw0] [ 20%] PASSED tests/test_consolidation_prompt.py::test_no_negative_example_blocks 
tests/test_consolidation_prompt.py::test_format_fills_placeholders 
tests/test_consolidator_core.py::test_parse_json_variants 
[gw3] [ 21%] PASSED tests/test_consolidation_prompt.py::test_format_fills_placeholders 
[gw0] [ 21%] PASSED tests/test_consolidator_core.py::test_parse_json_variants 
tests/test_consolidator_core.py::test_normalize_user_id 
tests/test_consolidator_core.py::test_merge_traits_dedupes 
[gw3] [ 21%] PASSED tests/test_consolidator_core.py::test_normalize_user_id 
[gw0] [ 22%] PASSED tests/test_consolidator_core.py::test_merge_traits_dedupes 
tests/test_consolidator_core.py::test_checkpoint_and_state_table 
tests/test_consolidator_core.py::test_fetch_next_messages_and_senders 
[gw1] [ 22%] PASSED tests/test_compressor.py::test_weekly_atomizes_long_memory 
[gw2] [ 23%] PASSED tests/test_candidate_reinforcement.py::test_quota_dry_run_does_not_archive 
tests/test_consolidation_prompt.py::test_attribution_clause_present 
tests/test_consolidation_prompt.py::test_no_hard_confidence_floor 
[gw1] [ 23%] PASSED tests/test_consolidation_prompt.py::test_no_hard_confidence_floor 
[gw2] [ 24%] PASSED tests/test_consolidation_prompt.py::test_attribution_clause_present 
tests/test_consolidator_core.py::test_write_user_profiles_new_and_merge 
tests/test_consolidator_core.py::test_write_short_term_upsert 
[gw0] [ 24%] PASSED tests/test_consolidator_core.py::test_fetch_next_messages_and_senders 
[gw3] [ 25%] PASSED tests/test_consolidator_core.py::test_checkpoint_and_state_table 
tests/test_consolidator_core.py::test_count_new_messages_and_has_new 
tests/test_consolidator_core.py::test_fetch_next_messages_source_kind_at_mention 
[gw1] [ 25%] PASSED tests/test_consolidator_core.py::test_write_short_term_upsert 
tests/test_consolidator_core.py::test_write_memory_candidates_whitelist 
[gw2] [ 26%] PASSED tests/test_consolidator_core.py::test_write_user_profiles_new_and_merge 
tests/test_consolidator_core.py::test_write_long_term_memories 
[gw3] [ 26%] PASSED tests/test_consolidator_core.py::test_fetch_next_messages_source_kind_at_mention 
tests/test_context_tail.py::test_summary_and_tail_coexist 
[gw0] [ 26%] PASSED tests/test_consolidator_core.py::test_count_new_messages_and_has_new 
tests/test_consolidator_core.py::test_build_prompt_and_fetch_summary 
[gw3] [ 27%] PASSED tests/test_context_tail.py::test_summary_and_tail_coexist 
tests/test_context_tail.py::test_tail_in_time_order 
[gw3] [ 27%] PASSED tests/test_context_tail.py::test_tail_in_time_order 
tests/test_cross_user_isolation.py::test_candidate_promotion_does_not_merge_across_users 
[gw2] [ 28%] PASSED tests/test_consolidator_core.py::test_write_long_term_memories 
tests/test_context_tail.py::test_bot_self_rendered_as_wo 
[gw2] [ 28%] PASSED tests/test_context_tail.py::test_bot_self_rendered_as_wo 
tests/test_cross_user_isolation.py::test_compressor_still_merges_same_user 
[gw3] [ 29%] PASSED tests/test_cross_user_isolation.py::test_candidate_promotion_does_not_merge_across_users 
tests/test_cross_user_isolation.py::test_compressor_does_not_merge_across_users 
[gw1] [ 29%] PASSED tests/test_consolidator_core.py::test_write_memory_candidates_whitelist 
[gw2] [ 30%] PASSED tests/test_cross_user_isolation.py::test_compressor_still_merges_same_user 
tests/test_context_tail.py::test_no_tail_falls_back_to_exchanges 
tests/test_cross_user_isolation.py::test_retrieval_merge_similar_keeps_users_separate 
[gw2] [ 30%] PASSED tests/test_cross_user_isolation.py::test_retrieval_merge_similar_keeps_users_separate 
[gw3] [ 31%] PASSED tests/test_cross_user_isolation.py::test_compressor_does_not_merge_across_users 
tests/test_db_cleaner.py::test_clean_db_missing_file 
tests/test_cross_user_isolation.py::test_retrieval_merge_similar_still_merges_same_user 
[gw3] [ 31%] PASSED tests/test_cross_user_isolation.py::test_retrieval_merge_similar_still_merges_same_user 
[gw1] [ 31%] PASSED tests/test_context_tail.py::test_no_tail_falls_back_to_exchanges 
tests/test_db_cleaner.py::test_trim_group_messages_missing_db 
[gw2] [ 32%] PASSED tests/test_db_cleaner.py::test_clean_db_missing_file 
tests/test_db_cleaner.py::test_clean_db_clears_tables_and_resets_seq 
[gw3] [ 32%] PASSED tests/test_db_cleaner.py::test_trim_group_messages_missing_db 
tests/test_db_cleaner.py::test_trim_group_messages_keeps_recent 
tests/test_db_cleaner.py::test_needs_cleanup_logic 
[gw0] [ 33%] PASSED tests/test_consolidator_core.py::test_build_prompt_and_fetch_summary 
[gw3] [ 33%] PASSED tests/test_db_cleaner.py::test_needs_cleanup_logic 
tests/test_context_tail.py::test_bot_question_precedes_user_reply 
tests/test_embeddings.py::test_normalize_and_cosine 
[gw3] [ 34%] PASSED tests/test_embeddings.py::test_normalize_and_cosine 
tests/test_embeddings.py::test_embedding_service_caches_and_calls 
[gw0] [ 34%] PASSED tests/test_context_tail.py::test_bot_question_precedes_user_reply 
tests/test_embeddings.py::test_cosine_mismatched_dim_returns_zero 
[gw1] [ 35%] PASSED tests/test_db_cleaner.py::test_clean_db_clears_tables_and_resets_seq 
[gw0] [ 35%] PASSED tests/test_embeddings.py::test_cosine_mismatched_dim_returns_zero 
[gw2] [ 36%] PASSED tests/test_db_cleaner.py::test_trim_group_messages_keeps_recent 
tests/test_db_cleaner.py::test_mark_cleanup_done_handles_error 
tests/test_embeddings.py::test_embedding_service_empty_text 
[gw0] [ 36%] PASSED tests/test_embeddings.py::test_embedding_service_empty_text 
[gw2] [ 36%] PASSED tests/test_db_cleaner.py::test_mark_cleanup_done_handles_error 
tests/test_db_cleaner.py::test_print_summary_runs 
tests/test_embeddings.py::test_rank_memories_uses_injected_semantic_scores 
tests/test_embeddings.py::test_retrieve_memories_emb_routes_semantic_scores 
[gw0] [ 37%] PASSED tests/test_embeddings.py::test_rank_memories_uses_injected_semantic_scores 
tests/test_full_workflow.py::test_full_workflow_chat_message_to_reply 
[gw2] [ 37%] PASSED tests/test_embeddings.py::test_retrieve_memories_emb_routes_semantic_scores 
tests/test_full_workflow.py::test_full_workflow_consolidation_promotes_memory 
[gw1] [ 38%] PASSED tests/test_db_cleaner.py::test_print_summary_runs 
tests/test_embeddings.py::test_retrieve_memories_emb_falls_back_on_service_failure 
[gw1] [ 38%] PASSED tests/test_embeddings.py::test_retrieve_memories_emb_falls_back_on_service_failure 
tests/test_lm_studio.py::test_constructor_normalizes_url 
[gw1] [ 39%] PASSED tests/test_lm_studio.py::test_constructor_normalizes_url 
tests/test_lm_studio.py::test_generate_success_path 
[gw1] [ 39%] PASSED tests/test_lm_studio.py::test_generate_success_path 
tests/test_lm_studio.py::test_generate_retries_on_empty_reply 
[gw1] [ 40%] PASSED tests/test_lm_studio.py::test_generate_retries_on_empty_reply 
tests/test_lm_studio.py::test_generate_gives_up_on_4xx 
[gw0] [ 40%] PASSED tests/test_full_workflow.py::test_full_workflow_chat_message_to_reply 
tests/test_full_workflow.py::test_full_workflow_summary_feeds_next_reply 
[gw1] [ 41%] PASSED tests/test_lm_studio.py::test_generate_gives_up_on_4xx 
tests/test_lm_studio.py::test_generate_exhausts_retries_on_generic_error 
[gw2] [ 41%] PASSED tests/test_full_workflow.py::test_full_workflow_consolidation_promotes_memory 
tests/test_full_workflow.py::test_full_workflow_force_consolidation_small_batch 
[gw3] [ 42%] PASSED tests/test_embeddings.py::test_embedding_service_caches_and_calls 
tests/test_embeddings.py::test_embedding_service_degrades_on_failure 
[gw0] [ 42%] PASSED tests/test_full_workflow.py::test_full_workflow_summary_feeds_next_reply 
tests/test_memory_manager.py::test_low_value_candidate_goes_to_observing 
[gw2] [ 42%] PASSED tests/test_full_workflow.py::test_full_workflow_force_consolidation_small_batch 
tests/test_memory_manager_fts_sync.py::test_fts_index_stays_in_sync_after_promotion 
[gw0] [ 43%] PASSED tests/test_memory_manager.py::test_low_value_candidate_goes_to_observing 
tests/test_memory_manager_fts_sync.py::test_fts_disabled_means_no_index_and_query_falls_back 
[gw3] [ 43%] PASSED tests/test_embeddings.py::test_embedding_service_degrades_on_failure 
[gw2] [ 44%] PASSED tests/test_memory_manager_fts_sync.py::test_fts_index_stays_in_sync_after_promotion 
tests/test_memory_manager_fts_sync.py::test_fts_index_sync_after_merge_updates_content 
tests/test_memory_manager_fts_sync.py::test_fts_rebuilds_when_index_is_stale 
[gw0] [ 44%] PASSED tests/test_memory_manager_fts_sync.py::test_fts_disabled_means_no_index_and_query_falls_back 
tests/test_memory_manager_v2.py::test_detect_contradiction 
[gw0] [ 45%] PASSED tests/test_memory_manager_v2.py::test_detect_contradiction 
tests/test_pipeline_compose.py::test_normal_reply_context_before_message 
[gw0] [ 45%] PASSED tests/test_pipeline_compose.py::test_normal_reply_context_before_message 
tests/test_pipeline_compose.py::test_proactive_at_instruction_before_context 
[gw0] [ 46%] PASSED tests/test_pipeline_compose.py::test_proactive_at_instruction_before_context 
tests/test_pipeline_compose.py::test_proactive_at_no_context_returns_instruction 
[gw0] [ 46%] PASSED tests/test_pipeline_compose.py::test_proactive_at_no_context_returns_instruction 
tests/test_pipeline_compose.py::test_normal_no_context_returns_message 
[gw0] [ 47%] PASSED tests/test_pipeline_compose.py::test_normal_no_context_returns_message 
tests/test_policy.py::test_usage_blocked_when_not_in_mode 
[gw0] [ 47%] PASSED tests/test_policy.py::test_usage_blocked_when_not_in_mode 
[gw2] [ 47%] PASSED tests/test_memory_manager_fts_sync.py::test_fts_rebuilds_when_index_is_stale 
tests/test_policy.py::test_usage_allowed_when_in_mode 
tests/test_memory_manager_v2.py::test_candidate_meta_fields_persisted 
[gw0] [ 48%] PASSED tests/test_policy.py::test_usage_allowed_when_in_mode 
tests/test_policy.py::test_boundary_never_chat_material_in_casual 
[gw0] [ 48%] PASSED tests/test_policy.py::test_boundary_never_chat_material_in_casual 
tests/test_policy.py::test_visibility_restricted_allowed_in_conflict 
[gw0] [ 49%] PASSED tests/test_policy.py::test_visibility_restricted_allowed_in_conflict 
tests/test_policy.py::test_detect_mode_tech_and_recommend 
[gw3] [ 49%] PASSED tests/test_memory_manager_fts_sync.py::test_fts_index_sync_after_merge_updates_content 
[gw0] [ 50%] PASSED tests/test_policy.py::test_detect_mode_tech_and_recommend 
tests/test_memory_manager_v2.py::test_conflict_marks_old_memory 
tests/test_policy.py::test_detect_mode_proactive 
[gw0] [ 50%] PASSED tests/test_policy.py::test_detect_mode_proactive 
tests/test_policy.py::test_detect_mode_ignore_daily_grumbling_conflict 
[gw0] [ 51%] PASSED tests/test_policy.py::test_detect_mode_ignore_daily_grumbling_conflict 
tests/test_policy.py::test_detect_mode_scoring_beats_priority_chain 
[gw0] [ 51%] PASSED tests/test_policy.py::test_detect_mode_scoring_beats_priority_chain 
tests/test_policy.py::test_rank_contextual_blocked_when_unrelated 
[gw0] [ 52%] PASSED tests/test_policy.py::test_rank_contextual_blocked_when_unrelated 
tests/test_policy.py::test_rank_contextual_exempted_by_strong_usage 
[gw0] [ 52%] PASSED tests/test_policy.py::test_rank_contextual_exempted_by_strong_usage 
tests/test_policy.py::test_rank_contextual_exempted_by_trigger_topic 
[gw0] [ 52%] PASSED tests/test_policy.py::test_rank_contextual_exempted_by_trigger_topic 
tests/test_policy.py::test_trigger_topic_match_keywords_and_topics 
[gw2] [ 53%] PASSED tests/test_memory_manager_v2.py::test_candidate_meta_fields_persisted 
tests/test_policy.py::test_visibility_restricted_denied_in_casual 
[gw0] [ 53%] PASSED tests/test_policy.py::test_trigger_topic_match_keywords_and_topics 
[gw2] [ 54%] PASSED tests/test_policy.py::test_visibility_restricted_denied_in_casual 
tests/test_policy.py::test_rank_memories_attaches_score 
tests/test_policy.py::test_rank_places_mode_matched_higher 
[gw0] [ 54%] PASSED tests/test_policy.py::test_rank_memories_attaches_score 
tests/test_policy.py::test_split_behavior_constraints 
[gw2] [ 55%] PASSED tests/test_policy.py::test_rank_places_mode_matched_higher 
[gw0] [ 55%] PASSED tests/test_policy.py::test_split_behavior_constraints 
tests/test_policy.py::test_validate_candidate_corrects_boundary_mislabel 
tests/test_policy.py::test_stable_profile_facts_filters_persona 
[gw2] [ 56%] PASSED tests/test_policy.py::test_validate_candidate_corrects_boundary_mislabel 
[gw0] [ 56%] PASSED tests/test_policy.py::test_stable_profile_facts_filters_persona 
[gw3] [ 57%] PASSED tests/test_memory_manager_v2.py::test_conflict_marks_old_memory 
tests/test_proactive_at_flow.py::test_record_at_counts_and_persists 
tests/test_policy.py::test_detect_mode_echo_noise_stays_casual 
tests/test_proactive_at_flow.py::test_no_reply_accumulates_then_resets 
[gw3] [ 57%] PASSED tests/test_policy.py::test_detect_mode_echo_noise_stays_casual 
tests/test_proactive_prompt.py::test_verify_instruction_contains_content_and_rules 
[gw2] [ 57%] PASSED tests/test_proactive_at_flow.py::test_record_at_counts_and_persists 
[gw3] [ 58%] PASSED tests/test_proactive_prompt.py::test_verify_instruction_contains_content_and_rules 
tests/test_proactive_at_flow.py::test_quota_is_per_user 
tests/test_proactive_prompt.py::test_coldstart_instruction_contains_topic 
[gw0] [ 58%] PASSED tests/test_proactive_at_flow.py::test_no_reply_accumulates_then_resets 
tests/test_proactive_at_flow.py::test_last_spoke_ts_detects_reply 
[gw0] [ 59%] PASSED tests/test_proactive_at_flow.py::test_last_spoke_ts_detects_reply 
[gw3] [ 59%] PASSED tests/test_proactive_prompt.py::test_coldstart_instruction_contains_topic 
tests/test_proactive_prompt.py::test_no_placeholder_left 
[gw2] [ 60%] PASSED tests/test_proactive_at_flow.py::test_quota_is_per_user 
tests/test_proactive_prompt.py::test_context_role_clause_present 
[gw0] [ 60%] PASSED tests/test_proactive_prompt.py::test_context_role_clause_present 
[gw3] [ 61%] PASSED tests/test_proactive_prompt.py::test_no_placeholder_left 
tests/test_proactive_rules.py::test_silent_group_never_speaks 
tests/test_proactive_prompt.py::test_common_rules_present_in_both 
[gw0] [ 61%] PASSED tests/test_proactive_rules.py::test_silent_group_never_speaks 
tests/test_proactive_prompt.py::test_build_instruction_dispatches_by_mode 
[gw2] [ 62%] PASSED tests/test_proactive_prompt.py::test_common_rules_present_in_both 
tests/test_proactive_rules.py::test_too_low_frequency_never_speaks 
[gw3] [ 62%] PASSED tests/test_proactive_prompt.py::test_build_instruction_dispatches_by_mode 
tests/test_proactive_rules.py::test_previous_logic_still_respects_cooldown 
[gw0] [ 63%] PASSED tests/test_proactive_rules.py::test_too_low_frequency_never_speaks 
[gw2] [ 63%] PASSED tests/test_proactive_rules.py::test_previous_logic_still_respects_cooldown 
tests/test_proactive_rules.py::test_ngrams_is_reasonable 
[gw0] [ 63%] PASSED tests/test_proactive_rules.py::test_ngrams_is_reasonable 
tests/test_proactive_rules.py::test_recently_spoken_dedup 
[gw3] [ 64%] PASSED tests/test_proactive_rules.py::test_recently_spoken_dedup 
tests/test_proactive_rules.py::test_group_interval_aggregated_across_users 
tests/test_proactive_rules.py::test_user_average_interval_requires_two 
[gw0] [ 64%] PASSED tests/test_proactive_rules.py::test_user_average_interval_requires_two 
tests/test_proactive_rules.py::test_active_users_filters_window_and_sorts_desc 
[gw2] [ 65%] PASSED tests/test_proactive_rules.py::test_group_interval_aggregated_across_users 
[gw3] [ 65%] PASSED tests/test_proactive_rules.py::test_active_users_filters_window_and_sorts_desc 
tests/test_proactive_rules.py::test_curve_at_fast_anchor 
tests/test_proactive_rules.py::test_curve_midpoint_between_anchors 
[gw0] [ 66%] PASSED tests/test_proactive_rules.py::test_curve_at_fast_anchor 
tests/test_proactive_rules.py::test_curve_at_slow_anchor 
[gw2] [ 66%] PASSED tests/test_proactive_rules.py::test_curve_at_slow_anchor 
[gw3] [ 67%] PASSED tests/test_proactive_rules.py::test_curve_midpoint_between_anchors 
tests/test_proactive_rules.py::test_curve_gamma_2_lower_than_gamma_1 
[gw0] [ 67%] PASSED tests/test_proactive_rules.py::test_curve_gamma_2_lower_than_gamma_1 
tests/test_proactive_state.py::test_at_count_increments 
tests/test_proactive_rules.py::test_curve_bad_anchor_no_error 
[gw3] [ 68%] PASSED tests/test_proactive_rules.py::test_curve_bad_anchor_no_error 
tests/test_proactive_state.py::test_cross_day_resets_count 
tests/test_proactive_state.py::test_consecutive_no_reply_increment_and_reset 
[gw2] [ 68%] PASSED tests/test_proactive_state.py::test_at_count_increments 
[gw0] [ 68%] PASSED tests/test_proactive_state.py::test_cross_day_resets_count 
tests/test_proactive_state.py::test_count_user_messages_24h_excludes_bot_self 
tests/test_proactive_state.py::test_missing_table_returns_defaults_without_error 
[gw3] [ 69%] PASSED tests/test_proactive_state.py::test_consecutive_no_reply_increment_and_reset 
[gw0] [ 69%] PASSED tests/test_proactive_state.py::test_missing_table_returns_defaults_without_error 
[gw2] [ 70%] PASSED tests/test_proactive_state.py::test_count_user_messages_24h_excludes_bot_self 
tests/test_proactive_target.py::test_at_quota_bad_bounds_no_error 
tests/test_proactive_target.py::test_at_quota_interpolation 
tests/test_proactive_target.py::test_cooldown_elapsed_variants 
[gw0] [ 70%] PASSED tests/test_proactive_target.py::test_cooldown_elapsed_variants 
[gw2] [ 71%] PASSED tests/test_proactive_target.py::test_at_quota_bad_bounds_no_error 
tests/test_proactive_target.py::test_can_at_user_quota_full 
[gw3] [ 71%] PASSED tests/test_proactive_target.py::test_at_quota_interpolation 
tests/test_proactive_target.py::test_can_at_user_quota_with_record_at_flow 
tests/test_proactive_target.py::test_can_at_user_no_reply_backoff 
[gw0] [ 72%] PASSED tests/test_proactive_target.py::test_can_at_user_quota_full 
[gw2] [ 72%] PASSED tests/test_proactive_target.py::test_can_at_user_quota_with_record_at_flow 
tests/test_proactive_target.py::test_can_at_user_disabled 
[gw3] [ 73%] PASSED tests/test_proactive_target.py::test_can_at_user_no_reply_backoff 
[gw0] [ 73%] PASSED tests/test_proactive_target.py::test_can_at_user_disabled 
tests/test_proactive_target.py::test_pick_target_no_active_users 
tests/test_proactive_target.py::test_pick_target_verify_prefers_highest_confidence 
[gw2] [ 73%] PASSED tests/test_proactive_target.py::test_pick_target_no_active_users 
tests/test_proactive_target.py::test_pick_target_verify_mode 
tests/test_proactive_target.py::test_pick_target_coldstart_avoids_last_topic 
[gw0] [ 74%] PASSED tests/test_proactive_target.py::test_pick_target_verify_prefers_highest_confidence 
[gw3] [ 74%] PASSED tests/test_proactive_target.py::test_pick_target_verify_mode 
tests/test_proactive_target.py::test_pick_target_exclude_user_ids 
tests/test_proactive_target.py::test_fetch_observing_candidate_window 
[gw3] [ 75%] PASSED tests/test_proactive_target.py::test_fetch_observing_candidate_window 
[gw0] [ 75%] PASSED tests/test_proactive_target.py::test_pick_target_exclude_user_ids 
tests/test_proactive_target.py::test_target_nickname_default 
tests/test_prompt_builder_v2.py::test_build_v2_prompt_context_partitions_sections 
[gw0] [ 76%] PASSED tests/test_proactive_target.py::test_target_nickname_default 
[gw3] [ 76%] PASSED tests/test_prompt_builder_v2.py::test_build_v2_prompt_context_partitions_sections 
tests/test_prompt_builder_v2.py::test_tech_mode_has_larger_conversation_budget 
tests/test_prompt_builder_v2.py::test_build_v2_prompt_context_omits_empty_sections 
[gw3] [ 77%] PASSED tests/test_prompt_builder_v2.py::test_build_v2_prompt_context_omits_empty_sections 
[gw0] [ 77%] PASSED tests/test_prompt_builder_v2.py::test_tech_mode_has_larger_conversation_budget 
tests/test_rag_switches.py::test_rag_disabled_uses_weighted_fallback_ranking 
tests/test_prompt_builder_v2.py::test_trace_records_and_statistics 
[gw0] [ 78%] PASSED tests/test_prompt_builder_v2.py::test_trace_records_and_statistics 
[gw3] [ 78%] PASSED tests/test_rag_switches.py::test_rag_disabled_uses_weighted_fallback_ranking 
tests/test_rag_switches.py::test_get_user_memories_query_scopes_to_user 
tests/test_rag_switches.py::test_fts_disabled_minnes_total_also_digit_ranking 
[gw0] [ 78%] PASSED tests/test_rag_switches.py::test_get_user_memories_query_scopes_to_user 
[gw3] [ 79%] PASSED tests/test_rag_switches.py::test_fts_disabled_minnes_total_also_digit_ranking 
tests/test_rag_switches.py::test_rag_disabled_does_not_create_fts_table 
tests/test_rag_switches.py::test_rag_top_k_sets_candidate_pool_floor 
[gw2] [ 79%] FAILED tests/test_proactive_target.py::test_pick_target_coldstart_avoids_last_topic 
tests/test_proactive_target.py::test_topic_covered_variants 
[gw2] [ 80%] PASSED tests/test_proactive_target.py::test_topic_covered_variants 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_proactive_uses_group_memories 
[gw0] [ 80%] PASSED tests/test_rag_switches.py::test_rag_disabled_does_not_create_fts_table 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_filters_restricted_in_casual 
[gw3] [ 81%] PASSED tests/test_rag_switches.py::test_rag_top_k_sets_candidate_pool_floor 
[gw2] [ 81%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_proactive_uses_group_memories 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_fts_path_returns_qualified_columns 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_conflict_mode_activates_behavior_guard 
[gw0] [ 82%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_filters_restricted_in_casual 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_score_floor_filters_noise 
[gw3] [ 82%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_conflict_mode_activates_behavior_guard 
[gw2] [ 83%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_fts_path_returns_qualified_columns 
tests/test_retrieval_v2_and_schema.py::test_schema_migration_does_not_touch_existing_data 
[gw0] [ 83%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_score_floor_filters_noise 
tests/test_retrieval_v2_and_schema.py::test_schema_migration_adds_columns 
tests/test_retriever.py::test_related_memories_are_ranked_by_relevance_and_recency 
[gw0] [ 84%] PASSED tests/test_retriever.py::test_related_memories_are_ranked_by_relevance_and_recency 
tests/test_retriever.py::test_group_memories_query_prefers_rag_results 
[gw3] [ 84%] PASSED tests/test_retrieval_v2_and_schema.py::test_schema_migration_does_not_touch_existing_data 
tests/test_retriever.py::test_related_memories_use_sqlite_rag_index 
[gw0] [ 84%] PASSED tests/test_retriever.py::test_group_memories_query_prefers_rag_results 
tests/test_retriever.py::test_user_memories_query_prefers_rag_results 
[gw3] [ 85%] PASSED tests/test_retriever.py::test_related_memories_use_sqlite_rag_index 
[gw2] [ 85%] PASSED tests/test_retrieval_v2_and_schema.py::test_schema_migration_adds_columns 
tests/test_short_term_attribution.py::test_write_and_read_short_term_keeps_attribution 
tests/test_retriever.py::test_group_memories_prefer_recent_and_important_entries 
[gw0] [ 86%] PASSED tests/test_retriever.py::test_user_memories_query_prefers_rag_results 
[gw2] [ 86%] PASSED tests/test_retriever.py::test_group_memories_prefer_recent_and_important_entries 
tests/test_short_term_attribution.py::test_build_context_falls_back_when_column_missing 
tests/test_short_term_attribution.py::test_memory_candidates_drop_unknown_sender 
[gw0] [ 87%] PASSED tests/test_short_term_attribution.py::test_build_context_falls_back_when_column_missing 
tests/test_short_term_attribution.py::test_prompt_builder_attributes_current_user 
[gw0] [ 87%] PASSED tests/test_short_term_attribution.py::test_prompt_builder_attributes_current_user 
tests/test_source_kind.py::test_passive_messages_get_no_marker 
[gw0] [ 88%] PASSED tests/test_source_kind.py::test_passive_messages_get_no_marker 
tests/test_source_kind.py::test_at_mention_messages_get_marker 
[gw3] [ 88%] PASSED tests/test_short_term_attribution.py::test_write_and_read_short_term_keeps_attribution 
[gw0] [ 89%] PASSED tests/test_source_kind.py::test_at_mention_messages_get_marker 
tests/test_short_term_attribution.py::test_fetch_current_summary_includes_exchanges 
tests/test_text_similarity.py::test_normalize_text_strips_punctuation_and_case 
[gw0] [ 89%] PASSED tests/test_text_similarity.py::test_normalize_text_strips_punctuation_and_case 
tests/test_text_similarity.py::test_is_similar_identical_and_substring 
[gw0] [ 89%] PASSED tests/test_text_similarity.py::test_is_similar_identical_and_substring 
tests/test_text_similarity.py::test_is_similar_rejects_unrelated 
[gw0] [ 90%] PASSED tests/test_text_similarity.py::test_is_similar_rejects_unrelated 
tests/test_text_similarity.py::test_is_similar_empty_is_never_similar 
[gw0] [ 90%] PASSED tests/test_text_similarity.py::test_is_similar_empty_is_never_similar 
[gw2] [ 91%] PASSED tests/test_short_term_attribution.py::test_memory_candidates_drop_unknown_sender 
tests/test_text_similarity.py::test_is_similar_threshold_is_configurable 
tests/test_short_term_attribution.py::test_consolidate_group_unpacks_senders 
[gw0] [ 91%] PASSED tests/test_text_similarity.py::test_is_similar_threshold_is_configurable 
tests/test_text_similarity.py::test_merge_content_prefers_more_complete 
[gw0] [ 92%] PASSED tests/test_text_similarity.py::test_merge_content_prefers_more_complete 
tests/test_text_similarity.py::test_merge_content_handles_empty 
[gw0] [ 92%] PASSED tests/test_text_similarity.py::test_merge_content_handles_empty 
tests/test_trace.py::test_record_trace_disabled 
[gw0] [ 93%] PASSED tests/test_trace.py::test_record_trace_disabled 
tests/test_trace.py::test_record_trace_creates_table_and_inserts 
[gw3] [ 93%] PASSED tests/test_short_term_attribution.py::test_fetch_current_summary_includes_exchanges 
tests/test_text_similarity.py::test_jaccard_edges 
[gw0] [ 94%] PASSED tests/test_trace.py::test_record_trace_creates_table_and_inserts 
tests/test_trace.py::test_record_trace_truncates_long_fields 
[gw3] [ 94%] PASSED tests/test_text_similarity.py::test_jaccard_edges 
tests/test_trace.py::test_record_trace_no_memory_fields 
[gw0] [ 94%] PASSED tests/test_trace.py::test_record_trace_truncates_long_fields 
[gw3] [ 95%] PASSED tests/test_trace.py::test_record_trace_no_memory_fields 
tests/test_trace.py::test_dump_and_parse_helpers 
tests/test_trace.py::test_memory_statistics 
[gw0] [ 95%] PASSED tests/test_trace.py::test_dump_and_parse_helpers 
tests/test_trace.py::test_memory_statistics_empty_and_missing_db 
[gw0] [ 96%] PASSED tests/test_trace.py::test_memory_statistics_empty_and_missing_db 
[gw3] [ 96%] PASSED tests/test_trace.py::test_memory_statistics 
tests/test_trace.py::test_prune_traces_no_db 
tests/test_trace.py::test_prune_traces 
[gw0] [ 97%] PASSED tests/test_trace.py::test_prune_traces_no_db 
tests/test_trace.py::test_statistics_on_broken_rows 
[gw3] [ 97%] PASSED tests/test_trace.py::test_prune_traces 
[gw0] [ 98%] PASSED tests/test_trace.py::test_statistics_on_broken_rows 
[gw2] [ 98%] PASSED tests/test_short_term_attribution.py::test_consolidate_group_unpacks_senders 
tests/test_text_similarity.py::test_merge_content_joins_distinct 
[gw2] [ 99%] PASSED tests/test_text_similarity.py::test_merge_content_joins_distinct 
[gw1] [ 99%] PASSED tests/test_lm_studio.py::test_generate_exhausts_retries_on_generic_error 
tests/test_memory_manager.py::test_high_value_candidate_becomes_confirmed_memory 
[gw1] [100%] PASSED tests/test_memory_manager.py::test_high_value_candidate_becomes_confirmed_memory 

==================================== ERRORS ====================================
___________________ ERROR collecting tests/test_benchmark.py ___________________
ImportError while importing test module '/home/runner/work/Stella_project/Stella_project/tests/test_benchmark.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_benchmark.py:9: in <module>
    import numpy as np
E   ModuleNotFoundError: No module named 'numpy'
=================================== FAILURES ===================================
_________________ test_pick_target_coldstart_avoids_last_topic _________________
[gw2] linux -- Python 3.11.15 /opt/hostedtoolcache/Python/3.11.15/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_pick_target_coldstart_avo0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f39aba0a910>

    def test_pick_target_coldstart_avoids_last_topic(tmp_path, monkeypatch):
        """无候选 → mode=coldstart，且 topic 不等于 last_asked_topic。"""
        _setup_db(monkeypatch, tmp_path)
        monkeypatch.setattr(pt, "PROACTIVE_COLDSTART_TOPICS", ["游戏话题", "美食话题"])
        monkeypatch.setattr(proactive.time, "monotonic", _faketicks())
        c = proactive.ProactiveController()
        monkeypatch.setattr(pt, "get_proactive", lambda: c)
        c.record_message(1, 2001)
        proactive_state.record_at(1, 2001, topic="游戏话题")
    
        target = pick_target(1)
>       assert target is not None
E       assert None is not None

tests/test_proactive_target.py:225: AssertionError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.15-final-0 _______________

Name                                    Stmts   Miss Branch BrPart  Cover
-------------------------------------------------------------------------
config/__init__.py                          1      0      0      0   100%
config/settings.py                        179     15     18      7    89%
core/__init__.py                            0      0      0      0   100%
core/context.py                            27      0      0      0   100%
core/llm/__init__.py                        3      0      0      0   100%
core/llm/base.py                            5      0      0      0   100%
core/llm/lm_studio.py                      54      3     14      3    91%
core/pipeline.py                           81     19     18      6    75%
memory/__init__.py                          0      0      0      0   100%
memory/benchmark.py                       250    111     70      5    51%
memory/compressor.py                      154     10     38      7    90%
memory/consolidation_log.py                11      0      2      0   100%
memory/consolidation_prompt.py              6      0      0      0   100%
memory/consolidator.py                    424     70    144     25    82%
memory/db_cleaner.py                       98     20     32      6    78%
memory/embeddings.py                       65      5     16      4    89%
memory/memory_manager.py                  229     14     72     10    91%
memory/policy.py                          316     39    124     15    85%
memory/post_processors.py                  61     10     20      9    74%
memory/pre_processors.py                  196     75     72     18    56%
memory/proactive.py                       106     12     28      6    85%
memory/proactive_prompt.py                 12      0      2      0   100%
memory/proactive_state.py                  52      7      4      0    88%
memory/proactive_target.py                109     21     38      5    81%
memory/prompt_builder.py                  105     36     54     11    62%
memory/retrieval_v2.py                    185     31     50     12    80%
memory/retriever.py                       242     32    112     28    83%
memory/schema.py                          148     42     50      7    67%
memory/text_similarity.py                  33      1     16      1    96%
memory/trace.py                            89     11     20      1    89%
tests/conftest.py                          10      0      0      0   100%
tests/test_benchmark.py                    63     60     16      0     4%
tests/test_benchmark_and_log.py            71      1      0      0    99%
tests/test_bot_self_source.py              64      0      0      0   100%
tests/test_candidate_reinforcement.py     176      0      8      0   100%
tests/test_compressor.py                  110      1      0      0    99%
tests/test_consolidation_prompt.py         26      0      2      0   100%
tests/test_consolidator_core.py           163      0      0      0   100%
tests/test_context_tail.py                 58      2      2      0    97%
tests/test_cross_user_isolation.py         61      0      0      0   100%
tests/test_db_cleaner.py                   77      0      2      0   100%
tests/test_embeddings.py                   99      3      8      2    95%
tests/test_full_workflow.py               147      0      2      0   100%
tests/test_lm_studio.py                    77      1      2      0    99%
tests/test_memory_manager.py               51      0      0      0   100%
tests/test_memory_manager_fts_sync.py      66      0      0      0   100%
tests/test_memory_manager_v2.py            54      0      0      0   100%
tests/test_pipeline_compose.py             17      0      0      0   100%
tests/test_policy.py                       80      0      0      0   100%
tests/test_proactive_at_flow.py            41      0      0      0   100%
tests/test_proactive_prompt.py             34      0      8      0   100%
tests/test_proactive_rules.py             124      0      0      0   100%
tests/test_proactive_state.py              46      0      0      0   100%
tests/test_proactive_target.py            158      3      6      0    98%
tests/test_prompt_builder_v2.py            38      0      0      0   100%
tests/test_rag_switches.py                 68      0      0      0   100%
tests/test_retrieval_v2_and_schema.py     124      0      2      0   100%
tests/test_retriever.py                    78      0      0      0   100%
tests/test_short_term_attribution.py      107      0      0      0   100%
tests/test_source_kind.py                  25      0      0      0   100%
tests/test_text_similarity.py              32      0      0      0   100%
tests/test_trace.py                        99      0      0      0   100%
-------------------------------------------------------------------------
TOTAL                                    5685    655   1072    188    85%
=========================== short test summary info ============================
FAILED tests/test_proactive_target.py::test_pick_target_coldstart_avoids_last_topic - assert None is not None
ERROR tests/test_benchmark.py - ImportError while importing test module '/home/runner/work/Stella_project/Stella_project/tests/test_benchmark.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_benchmark.py:9: in <module>
    import numpy as np
E   ModuleNotFoundError: No module named 'numpy'
==================== 1 failed, 218 passed, 1 error in 7.53s ====================
Error: Process completed with exit code 1.

# test (3.12)

Run pytest tests/ \
  pytest tests/ \
    -v \
    --cov=. \
    --cov-branch \
    -n auto \
    --dist loadgroup
  shell: /usr/bin/bash -e {0}
  env:
    pythonLocation: /opt/hostedtoolcache/Python/3.12.13/x64
    PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.12.13/x64/lib/pkgconfig
    Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.13/x64
    Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.13/x64
    Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.13/x64
    LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.12.13/x64/lib
    COVERAGE_FILE: cov-3.12
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /opt/hostedtoolcache/Python/3.12.13/x64/bin/python
cachedir: .pytest_cache
rootdir: /home/runner/work/Stella_project/Stella_project
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2, xdist-3.8.0
created: 4/4 workers
4 workers [219 items]

scheduling tests via LoadGroupScheduling

tests/test_benchmark_and_log.py::test_evaluate_case_forbidden_reported 
tests/test_benchmark_and_log.py::test_evaluate_case_basic 
tests/test_benchmark_and_log.py::test_load_cases_list_and_broken 
tests/test_benchmark_and_log.py::test_load_cases_missing_dir 
[gw0] [  0%] PASSED tests/test_benchmark_and_log.py::test_load_cases_missing_dir 
[gw1] [  0%] PASSED tests/test_benchmark_and_log.py::test_load_cases_list_and_broken 
tests/test_benchmark_and_log.py::test_evaluate_case_expected_in_behavior_constraints 
tests/test_benchmark_and_log.py::test_run_benchmark_empty_dir 
[gw1] [  1%] PASSED tests/test_benchmark_and_log.py::test_run_benchmark_empty_dir 
tests/test_benchmark_and_log.py::test_consolidation_log_handles_error 
[gw1] [  1%] PASSED tests/test_benchmark_and_log.py::test_consolidation_log_handles_error 
tests/test_bot_self_source.py::test_record_message_persists_bot_self 
[gw1] [  2%] PASSED tests/test_bot_self_source.py::test_record_message_persists_bot_self 
tests/test_bot_self_source.py::test_fetch_next_messages_bot_self_marked_and_excluded 
[gw0] [  2%] PASSED tests/test_benchmark_and_log.py::test_evaluate_case_expected_in_behavior_constraints 
tests/test_benchmark_and_log.py::test_consolidation_log_append_and_create 
[gw1] [  3%] PASSED tests/test_bot_self_source.py::test_fetch_next_messages_bot_self_marked_and_excluded 
[gw0] [  3%] PASSED tests/test_benchmark_and_log.py::test_consolidation_log_append_and_create 
[gw3] [  4%] PASSED tests/test_benchmark_and_log.py::test_evaluate_case_forbidden_reported 
[gw2] [  4%] PASSED tests/test_benchmark_and_log.py::test_evaluate_case_basic 
tests/test_bot_self_source.py::test_mixed_window_three_markers 
tests/test_bot_self_source.py::test_write_memory_candidates_drops_bot_self_candidate 
tests/test_benchmark_and_log.py::test_evaluate_case_over_recall_respects_max_retrieved 
tests/test_benchmark_and_log.py::test_run_benchmark_sums_metrics 
[gw1] [  5%] PASSED tests/test_bot_self_source.py::test_mixed_window_three_markers 
tests/test_candidate_reinforcement.py::test_similar_wording_counts_as_same_fact 
[gw2] [  5%] PASSED tests/test_benchmark_and_log.py::test_run_benchmark_sums_metrics 
tests/test_candidate_reinforcement.py::test_same_content_different_users_stay_separate 
[gw3] [  5%] PASSED tests/test_benchmark_and_log.py::test_evaluate_case_over_recall_respects_max_retrieved 
tests/test_candidate_reinforcement.py::test_unrelated_facts_stay_separate 
[gw0] [  6%] PASSED tests/test_bot_self_source.py::test_write_memory_candidates_drops_bot_self_candidate 
tests/test_candidate_reinforcement.py::test_same_fact_accumulates_instead_of_duplicating 
[gw1] [  6%] PASSED tests/test_candidate_reinforcement.py::test_similar_wording_counts_as_same_fact 
tests/test_candidate_reinforcement.py::test_source_kinds_accumulate_across_observations 
[gw2] [  7%] PASSED tests/test_candidate_reinforcement.py::test_same_content_different_users_stay_separate 
[gw3] [  7%] PASSED tests/test_candidate_reinforcement.py::test_unrelated_facts_stay_separate 
tests/test_candidate_reinforcement.py::test_first_seen_at_not_refreshed_on_reoccurrence 
tests/test_candidate_reinforcement.py::test_confidence_capped_at_one 
[gw1] [  8%] PASSED tests/test_candidate_reinforcement.py::test_source_kinds_accumulate_across_observations 
[gw0] [  8%] PASSED tests/test_candidate_reinforcement.py::test_same_fact_accumulates_instead_of_duplicating 
tests/test_candidate_reinforcement.py::test_gate1_mid_confidence_passive_single_observation_waits 
tests/test_candidate_reinforcement.py::test_gate1_high_confidence_promotes_immediately 
[gw0] [  9%] PASSED tests/test_candidate_reinforcement.py::test_gate1_high_confidence_promotes_immediately 
[gw1] [  9%] PASSED tests/test_candidate_reinforcement.py::test_gate1_mid_confidence_passive_single_observation_waits 
tests/test_candidate_reinforcement.py::test_gate1_low_confidence_never_promotes_even_with_at_mention 
tests/test_candidate_reinforcement.py::test_gate1_importance_alone_does_not_promote 
[gw0] [ 10%] PASSED tests/test_candidate_reinforcement.py::test_gate1_importance_alone_does_not_promote 
[gw1] [ 10%] PASSED tests/test_candidate_reinforcement.py::test_gate1_low_confidence_never_promotes_even_with_at_mention 
tests/test_candidate_reinforcement.py::test_gate1_trivial_importance_blocked 
[gw0] [ 10%] PASSED tests/test_candidate_reinforcement.py::test_gate1_trivial_importance_blocked 
tests/test_candidate_reinforcement.py::test_reoccurrence_eventually_promotes_end_to_end 
tests/test_candidate_reinforcement.py::test_has_at_mention_tolerates_garbage 
[gw1] [ 11%] PASSED tests/test_candidate_reinforcement.py::test_has_at_mention_tolerates_garbage 
tests/test_candidate_reinforcement.py::test_stale_observing_candidate_rejected 
[gw2] [ 11%] PASSED tests/test_candidate_reinforcement.py::test_first_seen_at_not_refreshed_on_reoccurrence 
tests/test_candidate_reinforcement.py::test_gate1_mid_confidence_promotes_after_reoccurrence 
[gw2] [ 12%] PASSED tests/test_candidate_reinforcement.py::test_gate1_mid_confidence_promotes_after_reoccurrence 
tests/test_candidate_reinforcement.py::test_quota_dry_run_does_not_archive 
[gw3] [ 12%] PASSED tests/test_candidate_reinforcement.py::test_confidence_capped_at_one 
tests/test_candidate_reinforcement.py::test_gate1_at_mention_promotes_single_shot 
[gw3] [ 13%] PASSED tests/test_candidate_reinforcement.py::test_gate1_at_mention_promotes_single_shot 
tests/test_candidate_reinforcement.py::test_quota_is_per_user_and_per_group 
[gw2] [ 13%] PASSED tests/test_candidate_reinforcement.py::test_quota_dry_run_does_not_archive 
tests/test_candidate_reinforcement.py::test_quota_enforce_archives_weakest 
[gw1] [ 14%] PASSED tests/test_candidate_reinforcement.py::test_stale_observing_candidate_rejected 
tests/test_candidate_reinforcement.py::test_quota_score_handles_garbage 
[gw1] [ 14%] PASSED tests/test_candidate_reinforcement.py::test_quota_score_handles_garbage 
tests/test_compressor.py::test_weekly_atomizes_long_memory 
[gw3] [ 15%] PASSED tests/test_candidate_reinforcement.py::test_quota_is_per_user_and_per_group 
[gw1] [ 15%] PASSED tests/test_compressor.py::test_weekly_atomizes_long_memory 
tests/test_compressor.py::test_maybe_compress_light_runs_once 
tests/test_compressor.py::test_weekly_no_active_memories 
[gw0] [ 15%] PASSED tests/test_candidate_reinforcement.py::test_reoccurrence_eventually_promotes_end_to_end 
tests/test_candidate_reinforcement.py::test_quota_score_prefers_confirmed_and_recent 
[gw0] [ 16%] PASSED tests/test_candidate_reinforcement.py::test_quota_score_prefers_confirmed_and_recent 
[gw3] [ 16%] PASSED tests/test_compressor.py::test_weekly_no_active_memories 
[gw1] [ 17%] PASSED tests/test_compressor.py::test_maybe_compress_light_runs_once 
tests/test_consolidation_prompt.py::test_no_fabrication_clauses_present 
[gw0] [ 17%] PASSED tests/test_consolidation_prompt.py::test_no_fabrication_clauses_present 
tests/test_compressor.py::test_split_into_fragments_and_store 
tests/test_compressor.py::test_maybe_compress_skips_when_cooled_down 
tests/test_consolidation_prompt.py::test_attribution_clause_present 
[gw2] [ 18%] PASSED tests/test_candidate_reinforcement.py::test_quota_enforce_archives_weakest 
[gw0] [ 18%] PASSED tests/test_consolidation_prompt.py::test_attribution_clause_present 
tests/test_compressor.py::test_weekly_merges_duplicates 
tests/test_consolidation_prompt.py::test_describes_whom_criterion_present 
[gw0] [ 19%] PASSED tests/test_consolidation_prompt.py::test_describes_whom_criterion_present 
[gw3] [ 19%] PASSED tests/test_compressor.py::test_split_into_fragments_and_store 
tests/test_consolidation_prompt.py::test_no_negative_example_blocks 
[gw0] [ 20%] PASSED tests/test_consolidation_prompt.py::test_no_negative_example_blocks 
[gw1] [ 20%] PASSED tests/test_compressor.py::test_maybe_compress_skips_when_cooled_down 
tests/test_consolidation_prompt.py::test_format_fills_placeholders 
tests/test_consolidation_prompt.py::test_bot_self_clause_present 
[gw3] [ 21%] PASSED tests/test_consolidation_prompt.py::test_bot_self_clause_present 
tests/test_consolidation_prompt.py::test_empty_array_permission_present 
[gw1] [ 21%] PASSED tests/test_consolidation_prompt.py::test_empty_array_permission_present 
[gw0] [ 21%] PASSED tests/test_consolidation_prompt.py::test_format_fills_placeholders 
tests/test_consolidator_core.py::test_parse_json_variants 
[gw2] [ 22%] PASSED tests/test_compressor.py::test_weekly_merges_duplicates 
tests/test_consolidator_core.py::test_merge_traits_dedupes 
tests/test_consolidator_core.py::test_normalize_user_id 
[gw3] [ 22%] PASSED tests/test_consolidator_core.py::test_parse_json_variants 
[gw0] [ 23%] PASSED tests/test_consolidator_core.py::test_normalize_user_id 
[gw1] [ 23%] PASSED tests/test_consolidator_core.py::test_merge_traits_dedupes 
tests/test_consolidator_core.py::test_fetch_next_messages_source_kind_at_mention 
tests/test_consolidation_prompt.py::test_no_hard_confidence_floor 
[gw2] [ 24%] PASSED tests/test_consolidation_prompt.py::test_no_hard_confidence_floor 
tests/test_consolidator_core.py::test_checkpoint_and_state_table 
tests/test_consolidator_core.py::test_fetch_next_messages_and_senders 
tests/test_consolidator_core.py::test_count_new_messages_and_has_new 
[gw3] [ 24%] PASSED tests/test_consolidator_core.py::test_fetch_next_messages_source_kind_at_mention 
tests/test_consolidator_core.py::test_write_short_term_upsert 
[gw1] [ 25%] PASSED tests/test_consolidator_core.py::test_fetch_next_messages_and_senders 
tests/test_consolidator_core.py::test_write_user_profiles_new_and_merge 
[gw0] [ 25%] PASSED tests/test_consolidator_core.py::test_checkpoint_and_state_table 
tests/test_consolidator_core.py::test_write_memory_candidates_whitelist 
[gw2] [ 26%] PASSED tests/test_consolidator_core.py::test_count_new_messages_and_has_new 
tests/test_consolidator_core.py::test_write_long_term_memories 
[gw2] [ 26%] PASSED tests/test_consolidator_core.py::test_write_long_term_memories 
tests/test_context_tail.py::test_bot_self_rendered_as_wo 
[gw3] [ 26%] PASSED tests/test_consolidator_core.py::test_write_short_term_upsert 
[gw2] [ 27%] PASSED tests/test_context_tail.py::test_bot_self_rendered_as_wo 
tests/test_consolidator_core.py::test_build_prompt_and_fetch_summary 
tests/test_context_tail.py::test_tail_in_time_order 
[gw0] [ 27%] PASSED tests/test_consolidator_core.py::test_write_memory_candidates_whitelist 
tests/test_context_tail.py::test_no_tail_falls_back_to_exchanges 
[gw2] [ 28%] PASSED tests/test_context_tail.py::test_tail_in_time_order 
tests/test_cross_user_isolation.py::test_candidate_promotion_does_not_merge_across_users 
[gw1] [ 28%] PASSED tests/test_consolidator_core.py::test_write_user_profiles_new_and_merge 
tests/test_context_tail.py::test_summary_and_tail_coexist 
[gw0] [ 29%] PASSED tests/test_context_tail.py::test_no_tail_falls_back_to_exchanges 
tests/test_cross_user_isolation.py::test_compressor_does_not_merge_across_users 
[gw1] [ 29%] PASSED tests/test_context_tail.py::test_summary_and_tail_coexist 
tests/test_cross_user_isolation.py::test_retrieval_merge_similar_keeps_users_separate 
[gw0] [ 30%] PASSED tests/test_cross_user_isolation.py::test_compressor_does_not_merge_across_users 
[gw1] [ 30%] PASSED tests/test_cross_user_isolation.py::test_retrieval_merge_similar_keeps_users_separate 
tests/test_cross_user_isolation.py::test_retrieval_merge_similar_still_merges_same_user 
[gw0] [ 31%] PASSED tests/test_cross_user_isolation.py::test_retrieval_merge_similar_still_merges_same_user 
tests/test_db_cleaner.py::test_clean_db_clears_tables_and_resets_seq 
tests/test_db_cleaner.py::test_clean_db_missing_file 
[gw0] [ 31%] PASSED tests/test_db_cleaner.py::test_clean_db_missing_file 
tests/test_db_cleaner.py::test_trim_group_messages_missing_db 
[gw0] [ 31%] PASSED tests/test_db_cleaner.py::test_trim_group_messages_missing_db 
[gw2] [ 32%] PASSED tests/test_cross_user_isolation.py::test_candidate_promotion_does_not_merge_across_users 
tests/test_db_cleaner.py::test_needs_cleanup_logic 
tests/test_cross_user_isolation.py::test_compressor_still_merges_same_user 
[gw0] [ 32%] PASSED tests/test_db_cleaner.py::test_needs_cleanup_logic 
tests/test_db_cleaner.py::test_print_summary_runs 
[gw1] [ 33%] PASSED tests/test_db_cleaner.py::test_clean_db_clears_tables_and_resets_seq 
tests/test_db_cleaner.py::test_trim_group_messages_keeps_recent 
[gw3] [ 33%] PASSED tests/test_consolidator_core.py::test_build_prompt_and_fetch_summary 
[gw2] [ 34%] PASSED tests/test_cross_user_isolation.py::test_compressor_still_merges_same_user 
tests/test_context_tail.py::test_bot_question_precedes_user_reply 
tests/test_db_cleaner.py::test_mark_cleanup_done_handles_error 
[gw0] [ 34%] PASSED tests/test_db_cleaner.py::test_print_summary_runs 
[gw2] [ 35%] PASSED tests/test_db_cleaner.py::test_mark_cleanup_done_handles_error 
tests/test_embeddings.py::test_normalize_and_cosine 
[gw0] [ 35%] PASSED tests/test_embeddings.py::test_normalize_and_cosine 
tests/test_embeddings.py::test_embedding_service_degrades_on_failure 
tests/test_embeddings.py::test_embedding_service_empty_text 
[gw3] [ 36%] PASSED tests/test_context_tail.py::test_bot_question_precedes_user_reply 
[gw0] [ 36%] PASSED tests/test_embeddings.py::test_embedding_service_empty_text 
[gw1] [ 36%] PASSED tests/test_db_cleaner.py::test_trim_group_messages_keeps_recent 
tests/test_embeddings.py::test_retrieve_memories_emb_routes_semantic_scores 
tests/test_embeddings.py::test_embedding_service_caches_and_calls 
tests/test_embeddings.py::test_cosine_mismatched_dim_returns_zero 
[gw1] [ 37%] PASSED tests/test_embeddings.py::test_cosine_mismatched_dim_returns_zero 
tests/test_full_workflow.py::test_full_workflow_consolidation_promotes_memory 
[gw0] [ 37%] PASSED tests/test_embeddings.py::test_retrieve_memories_emb_routes_semantic_scores 
tests/test_full_workflow.py::test_full_workflow_chat_message_to_reply 
[gw0] [ 38%] PASSED tests/test_full_workflow.py::test_full_workflow_chat_message_to_reply 
tests/test_full_workflow.py::test_full_workflow_force_consolidation_small_batch 
[gw1] [ 38%] PASSED tests/test_full_workflow.py::test_full_workflow_consolidation_promotes_memory 
tests/test_full_workflow.py::test_full_workflow_summary_feeds_next_reply 
[gw0] [ 39%] PASSED tests/test_full_workflow.py::test_full_workflow_force_consolidation_small_batch 
tests/test_lm_studio.py::test_constructor_normalizes_url 
[gw0] [ 39%] PASSED tests/test_lm_studio.py::test_constructor_normalizes_url 
tests/test_lm_studio.py::test_generate_retries_on_empty_reply 
[gw0] [ 40%] PASSED tests/test_lm_studio.py::test_generate_retries_on_empty_reply 
[gw3] [ 40%] PASSED tests/test_embeddings.py::test_embedding_service_caches_and_calls 
tests/test_lm_studio.py::test_generate_gives_up_on_4xx 
tests/test_embeddings.py::test_retrieve_memories_emb_falls_back_on_service_failure 
[gw0] [ 41%] PASSED tests/test_lm_studio.py::test_generate_gives_up_on_4xx 
tests/test_lm_studio.py::test_generate_exhausts_retries_on_generic_error 
[gw3] [ 41%] PASSED tests/test_embeddings.py::test_retrieve_memories_emb_falls_back_on_service_failure 
tests/test_memory_manager.py::test_low_value_candidate_goes_to_observing 
[gw1] [ 42%] PASSED tests/test_full_workflow.py::test_full_workflow_summary_feeds_next_reply 
tests/test_lm_studio.py::test_generate_success_path 
[gw1] [ 42%] PASSED tests/test_lm_studio.py::test_generate_success_path 
tests/test_memory_manager_fts_sync.py::test_fts_index_sync_after_merge_updates_content 
[gw2] [ 42%] PASSED tests/test_embeddings.py::test_embedding_service_degrades_on_failure 
[gw3] [ 43%] PASSED tests/test_memory_manager.py::test_low_value_candidate_goes_to_observing 
tests/test_embeddings.py::test_rank_memories_uses_injected_semantic_scores 
tests/test_memory_manager_fts_sync.py::test_fts_index_stays_in_sync_after_promotion 
[gw2] [ 43%] PASSED tests/test_embeddings.py::test_rank_memories_uses_injected_semantic_scores 
tests/test_memory_manager_fts_sync.py::test_fts_rebuilds_when_index_is_stale 
[gw2] [ 44%] PASSED tests/test_memory_manager_fts_sync.py::test_fts_rebuilds_when_index_is_stale 
tests/test_memory_manager_v2.py::test_conflict_marks_old_memory 
[gw3] [ 44%] PASSED tests/test_memory_manager_fts_sync.py::test_fts_index_stays_in_sync_after_promotion 
tests/test_memory_manager_v2.py::test_detect_contradiction 
[gw3] [ 45%] PASSED tests/test_memory_manager_v2.py::test_detect_contradiction 
[gw1] [ 45%] PASSED tests/test_memory_manager_fts_sync.py::test_fts_index_sync_after_merge_updates_content 
tests/test_pipeline_compose.py::test_normal_reply_context_before_message 
tests/test_memory_manager_fts_sync.py::test_fts_disabled_means_no_index_and_query_falls_back 
[gw3] [ 46%] PASSED tests/test_pipeline_compose.py::test_normal_reply_context_before_message 
tests/test_pipeline_compose.py::test_proactive_at_instruction_before_context 
[gw3] [ 46%] PASSED tests/test_pipeline_compose.py::test_proactive_at_instruction_before_context 
tests/test_pipeline_compose.py::test_normal_no_context_returns_message 
[gw3] [ 47%] PASSED tests/test_pipeline_compose.py::test_normal_no_context_returns_message 
tests/test_policy.py::test_usage_blocked_when_not_in_mode 
[gw3] [ 47%] PASSED tests/test_policy.py::test_usage_blocked_when_not_in_mode 
tests/test_policy.py::test_usage_allowed_when_in_mode 
[gw3] [ 47%] PASSED tests/test_policy.py::test_usage_allowed_when_in_mode 
tests/test_policy.py::test_boundary_never_chat_material_in_casual 
[gw3] [ 48%] PASSED tests/test_policy.py::test_boundary_never_chat_material_in_casual 
tests/test_policy.py::test_visibility_restricted_denied_in_casual 
[gw2] [ 48%] PASSED tests/test_memory_manager_v2.py::test_conflict_marks_old_memory 
[gw3] [ 49%] PASSED tests/test_policy.py::test_visibility_restricted_denied_in_casual 
tests/test_memory_manager_v2.py::test_candidate_meta_fields_persisted 
tests/test_policy.py::test_visibility_restricted_allowed_in_conflict 
[gw3] [ 49%] PASSED tests/test_policy.py::test_visibility_restricted_allowed_in_conflict 
tests/test_policy.py::test_detect_mode_proactive 
[gw3] [ 50%] PASSED tests/test_policy.py::test_detect_mode_proactive 
tests/test_policy.py::test_detect_mode_echo_noise_stays_casual 
[gw3] [ 50%] PASSED tests/test_policy.py::test_detect_mode_echo_noise_stays_casual 
tests/test_policy.py::test_detect_mode_ignore_daily_grumbling_conflict 
[gw3] [ 51%] PASSED tests/test_policy.py::test_detect_mode_ignore_daily_grumbling_conflict 
tests/test_policy.py::test_detect_mode_scoring_beats_priority_chain 
[gw1] [ 51%] PASSED tests/test_memory_manager_fts_sync.py::test_fts_disabled_means_no_index_and_query_falls_back 
[gw3] [ 52%] PASSED tests/test_policy.py::test_detect_mode_scoring_beats_priority_chain 
tests/test_pipeline_compose.py::test_proactive_at_no_context_returns_instruction 
tests/test_policy.py::test_rank_contextual_blocked_when_unrelated 
[gw1] [ 52%] PASSED tests/test_pipeline_compose.py::test_proactive_at_no_context_returns_instruction 
[gw3] [ 52%] PASSED tests/test_policy.py::test_rank_contextual_blocked_when_unrelated 
tests/test_policy.py::test_rank_contextual_exempted_by_trigger_topic 
tests/test_policy.py::test_rank_contextual_exempted_by_strong_usage 
[gw3] [ 53%] PASSED tests/test_policy.py::test_rank_contextual_exempted_by_trigger_topic 
[gw1] [ 53%] PASSED tests/test_policy.py::test_rank_contextual_exempted_by_strong_usage 
tests/test_policy.py::test_rank_memories_attaches_score 
tests/test_policy.py::test_trigger_topic_match_keywords_and_topics 
[gw3] [ 54%] PASSED tests/test_policy.py::test_rank_memories_attaches_score 
tests/test_policy.py::test_rank_places_mode_matched_higher 
[gw1] [ 54%] PASSED tests/test_policy.py::test_trigger_topic_match_keywords_and_topics 
[gw3] [ 55%] PASSED tests/test_policy.py::test_rank_places_mode_matched_higher 
tests/test_policy.py::test_split_behavior_constraints 
tests/test_policy.py::test_validate_candidate_corrects_boundary_mislabel 
[gw1] [ 55%] PASSED tests/test_policy.py::test_split_behavior_constraints 
[gw3] [ 56%] PASSED tests/test_policy.py::test_validate_candidate_corrects_boundary_mislabel 
tests/test_policy.py::test_stable_profile_facts_filters_persona 
tests/test_proactive_at_flow.py::test_record_at_counts_and_persists 
[gw1] [ 56%] PASSED tests/test_policy.py::test_stable_profile_facts_filters_persona 
[gw2] [ 57%] PASSED tests/test_memory_manager_v2.py::test_candidate_meta_fields_persisted 
tests/test_policy.py::test_detect_mode_tech_and_recommend 
tests/test_proactive_at_flow.py::test_no_reply_accumulates_then_resets 
[gw2] [ 57%] PASSED tests/test_policy.py::test_detect_mode_tech_and_recommend 
tests/test_proactive_at_flow.py::test_last_spoke_ts_detects_reply 
[gw3] [ 57%] PASSED tests/test_proactive_at_flow.py::test_record_at_counts_and_persists 
[gw2] [ 58%] PASSED tests/test_proactive_at_flow.py::test_last_spoke_ts_detects_reply 
tests/test_proactive_at_flow.py::test_quota_is_per_user 
tests/test_proactive_prompt.py::test_coldstart_instruction_contains_topic 
[gw2] [ 58%] PASSED tests/test_proactive_prompt.py::test_coldstart_instruction_contains_topic 
[gw1] [ 59%] PASSED tests/test_proactive_at_flow.py::test_no_reply_accumulates_then_resets 
tests/test_proactive_prompt.py::test_no_placeholder_left 
tests/test_proactive_prompt.py::test_verify_instruction_contains_content_and_rules 
[gw2] [ 59%] PASSED tests/test_proactive_prompt.py::test_no_placeholder_left 
[gw1] [ 60%] PASSED tests/test_proactive_prompt.py::test_verify_instruction_contains_content_and_rules 
[gw3] [ 60%] PASSED tests/test_proactive_at_flow.py::test_quota_is_per_user 
tests/test_proactive_prompt.py::test_context_role_clause_present 
tests/test_proactive_prompt.py::test_build_instruction_dispatches_by_mode 
[gw2] [ 61%] PASSED tests/test_proactive_prompt.py::test_context_role_clause_present 
[gw1] [ 61%] PASSED tests/test_proactive_prompt.py::test_build_instruction_dispatches_by_mode 
tests/test_proactive_prompt.py::test_common_rules_present_in_both 
[gw3] [ 62%] PASSED tests/test_proactive_prompt.py::test_common_rules_present_in_both 
tests/test_proactive_rules.py::test_too_low_frequency_never_speaks 
tests/test_proactive_rules.py::test_previous_logic_still_respects_cooldown 
tests/test_proactive_rules.py::test_silent_group_never_speaks 
[gw1] [ 62%] PASSED tests/test_proactive_rules.py::test_too_low_frequency_never_speaks 
[gw3] [ 63%] PASSED tests/test_proactive_rules.py::test_previous_logic_still_respects_cooldown 
[gw2] [ 63%] PASSED tests/test_proactive_rules.py::test_silent_group_never_speaks 
tests/test_proactive_rules.py::test_recently_spoken_dedup 
tests/test_proactive_rules.py::test_group_interval_aggregated_across_users 
[gw1] [ 63%] PASSED tests/test_proactive_rules.py::test_recently_spoken_dedup 
[gw2] [ 64%] PASSED tests/test_proactive_rules.py::test_group_interval_aggregated_across_users 
tests/test_proactive_rules.py::test_active_users_filters_window_and_sorts_desc 
tests/test_proactive_rules.py::test_ngrams_is_reasonable 
[gw3] [ 64%] PASSED tests/test_proactive_rules.py::test_ngrams_is_reasonable 
tests/test_proactive_rules.py::test_curve_at_fast_anchor 
[gw1] [ 65%] PASSED tests/test_proactive_rules.py::test_active_users_filters_window_and_sorts_desc 
tests/test_proactive_rules.py::test_user_average_interval_requires_two 
[gw2] [ 65%] PASSED tests/test_proactive_rules.py::test_user_average_interval_requires_two 
[gw3] [ 66%] PASSED tests/test_proactive_rules.py::test_curve_at_fast_anchor 
tests/test_proactive_rules.py::test_curve_midpoint_between_anchors 
tests/test_proactive_rules.py::test_curve_at_slow_anchor 
[gw2] [ 66%] PASSED tests/test_proactive_rules.py::test_curve_midpoint_between_anchors 
[gw1] [ 67%] PASSED tests/test_proactive_rules.py::test_curve_at_slow_anchor 
tests/test_proactive_rules.py::test_curve_gamma_2_lower_than_gamma_1 
[gw3] [ 67%] PASSED tests/test_proactive_rules.py::test_curve_gamma_2_lower_than_gamma_1 
tests/test_proactive_state.py::test_cross_day_resets_count 
tests/test_proactive_state.py::test_at_count_increments 
tests/test_proactive_rules.py::test_curve_bad_anchor_no_error 
[gw2] [ 68%] PASSED tests/test_proactive_rules.py::test_curve_bad_anchor_no_error 
[gw3] [ 68%] PASSED tests/test_proactive_state.py::test_cross_day_resets_count 
tests/test_proactive_state.py::test_count_user_messages_24h_excludes_bot_self 
tests/test_proactive_state.py::test_consecutive_no_reply_increment_and_reset 
[gw1] [ 68%] PASSED tests/test_proactive_state.py::test_at_count_increments 
tests/test_proactive_state.py::test_missing_table_returns_defaults_without_error 
[gw2] [ 69%] PASSED tests/test_proactive_state.py::test_count_user_messages_24h_excludes_bot_self 
tests/test_proactive_target.py::test_at_quota_interpolation 
[gw1] [ 69%] PASSED tests/test_proactive_state.py::test_missing_table_returns_defaults_without_error 
[gw2] [ 70%] PASSED tests/test_proactive_target.py::test_at_quota_interpolation 
tests/test_proactive_target.py::test_cooldown_elapsed_variants 
[gw3] [ 70%] PASSED tests/test_proactive_state.py::test_consecutive_no_reply_increment_and_reset 
tests/test_proactive_target.py::test_can_at_user_quota_full 
[gw1] [ 71%] PASSED tests/test_proactive_target.py::test_cooldown_elapsed_variants 
tests/test_proactive_target.py::test_at_quota_bad_bounds_no_error 
tests/test_proactive_target.py::test_can_at_user_quota_with_record_at_flow 
[gw3] [ 71%] PASSED tests/test_proactive_target.py::test_at_quota_bad_bounds_no_error 
tests/test_proactive_target.py::test_can_at_user_disabled 
[gw3] [ 72%] PASSED tests/test_proactive_target.py::test_can_at_user_disabled 
[gw2] [ 72%] PASSED tests/test_proactive_target.py::test_can_at_user_quota_full 
[gw1] [ 73%] PASSED tests/test_proactive_target.py::test_can_at_user_quota_with_record_at_flow 
tests/test_proactive_target.py::test_pick_target_verify_mode 
tests/test_proactive_target.py::test_can_at_user_no_reply_backoff 
tests/test_proactive_target.py::test_pick_target_no_active_users 
[gw1] [ 73%] PASSED tests/test_proactive_target.py::test_pick_target_no_active_users 
tests/test_proactive_target.py::test_pick_target_exclude_user_ids 
[gw3] [ 73%] PASSED tests/test_proactive_target.py::test_pick_target_verify_mode 
tests/test_proactive_target.py::test_pick_target_verify_prefers_highest_confidence 
[gw2] [ 74%] PASSED tests/test_proactive_target.py::test_can_at_user_no_reply_backoff 
tests/test_proactive_target.py::test_pick_target_coldstart_avoids_last_topic 
[gw1] [ 74%] PASSED tests/test_proactive_target.py::test_pick_target_exclude_user_ids 
tests/test_proactive_target.py::test_fetch_observing_candidate_window 
[gw3] [ 75%] PASSED tests/test_proactive_target.py::test_pick_target_verify_prefers_highest_confidence 
tests/test_proactive_target.py::test_topic_covered_variants 
[gw3] [ 75%] PASSED tests/test_proactive_target.py::test_topic_covered_variants 
[gw1] [ 76%] PASSED tests/test_proactive_target.py::test_fetch_observing_candidate_window 
tests/test_prompt_builder_v2.py::test_build_v2_prompt_context_partitions_sections 
tests/test_prompt_builder_v2.py::test_build_v2_prompt_context_omits_empty_sections 
[gw1] [ 76%] PASSED tests/test_prompt_builder_v2.py::test_build_v2_prompt_context_partitions_sections 
[gw3] [ 77%] PASSED tests/test_prompt_builder_v2.py::test_build_v2_prompt_context_omits_empty_sections 
tests/test_prompt_builder_v2.py::test_tech_mode_has_larger_conversation_budget 
tests/test_prompt_builder_v2.py::test_trace_records_and_statistics 
[gw1] [ 77%] PASSED tests/test_prompt_builder_v2.py::test_tech_mode_has_larger_conversation_budget 
[gw3] [ 78%] PASSED tests/test_prompt_builder_v2.py::test_trace_records_and_statistics 
tests/test_rag_switches.py::test_rag_disabled_uses_weighted_fallback_ranking 
tests/test_rag_switches.py::test_fts_disabled_minnes_total_also_digit_ranking 
[gw1] [ 78%] PASSED tests/test_rag_switches.py::test_rag_disabled_uses_weighted_fallback_ranking 
[gw3] [ 78%] PASSED tests/test_rag_switches.py::test_fts_disabled_minnes_total_also_digit_ranking 
tests/test_rag_switches.py::test_rag_disabled_does_not_create_fts_table 
tests/test_rag_switches.py::test_get_user_memories_query_scopes_to_user 
[gw3] [ 79%] PASSED tests/test_rag_switches.py::test_rag_disabled_does_not_create_fts_table 
tests/test_rag_switches.py::test_rag_top_k_sets_candidate_pool_floor 
[gw1] [ 79%] PASSED tests/test_rag_switches.py::test_get_user_memories_query_scopes_to_user 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_filters_restricted_in_casual 
[gw3] [ 80%] PASSED tests/test_rag_switches.py::test_rag_top_k_sets_candidate_pool_floor 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_conflict_mode_activates_behavior_guard 
[gw1] [ 80%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_filters_restricted_in_casual 
[gw3] [ 81%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_conflict_mode_activates_behavior_guard 
[gw2] [ 81%] FAILED tests/test_proactive_target.py::test_pick_target_coldstart_avoids_last_topic 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_fts_path_returns_qualified_columns 
tests/test_proactive_target.py::test_target_nickname_default 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_proactive_uses_group_memories 
[gw2] [ 82%] PASSED tests/test_proactive_target.py::test_target_nickname_default 
tests/test_retrieval_v2_and_schema.py::test_schema_migration_does_not_touch_existing_data 
[gw1] [ 82%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_proactive_uses_group_memories 
[gw3] [ 83%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_fts_path_returns_qualified_columns 
tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_score_floor_filters_noise 
tests/test_retrieval_v2_and_schema.py::test_schema_migration_adds_columns 
[gw1] [ 83%] PASSED tests/test_retrieval_v2_and_schema.py::test_retrieval_v2_score_floor_filters_noise 
tests/test_retriever.py::test_related_memories_use_sqlite_rag_index 
[gw2] [ 84%] PASSED tests/test_retrieval_v2_and_schema.py::test_schema_migration_does_not_touch_existing_data 
tests/test_retriever.py::test_related_memories_are_ranked_by_relevance_and_recency 
[gw1] [ 84%] PASSED tests/test_retriever.py::test_related_memories_use_sqlite_rag_index 
tests/test_retriever.py::test_group_memories_query_prefers_rag_results 
[gw2] [ 84%] PASSED tests/test_retriever.py::test_related_memories_are_ranked_by_relevance_and_recency 
tests/test_retriever.py::test_user_memories_query_prefers_rag_results 
[gw3] [ 85%] PASSED tests/test_retrieval_v2_and_schema.py::test_schema_migration_adds_columns 
[gw1] [ 85%] PASSED tests/test_retriever.py::test_group_memories_query_prefers_rag_results 
tests/test_retriever.py::test_group_memories_prefer_recent_and_important_entries 
tests/test_short_term_attribution.py::test_write_and_read_short_term_keeps_attribution 
[gw3] [ 86%] PASSED tests/test_retriever.py::test_group_memories_prefer_recent_and_important_entries 
[gw2] [ 86%] PASSED tests/test_retriever.py::test_user_memories_query_prefers_rag_results 
tests/test_short_term_attribution.py::test_fetch_current_summary_includes_exchanges 
tests/test_short_term_attribution.py::test_build_context_falls_back_when_column_missing 
[gw2] [ 87%] PASSED tests/test_short_term_attribution.py::test_build_context_falls_back_when_column_missing 
tests/test_short_term_attribution.py::test_consolidate_group_unpacks_senders 
[gw1] [ 87%] PASSED tests/test_short_term_attribution.py::test_write_and_read_short_term_keeps_attribution 
tests/test_short_term_attribution.py::test_memory_candidates_drop_unknown_sender 
[gw3] [ 88%] PASSED tests/test_short_term_attribution.py::test_fetch_current_summary_includes_exchanges 
tests/test_short_term_attribution.py::test_prompt_builder_attributes_current_user 
[gw3] [ 88%] PASSED tests/test_short_term_attribution.py::test_prompt_builder_attributes_current_user 
tests/test_text_similarity.py::test_normalize_text_strips_punctuation_and_case 
[gw3] [ 89%] PASSED tests/test_text_similarity.py::test_normalize_text_strips_punctuation_and_case 
tests/test_text_similarity.py::test_jaccard_edges 
[gw3] [ 89%] PASSED tests/test_text_similarity.py::test_jaccard_edges 
tests/test_text_similarity.py::test_is_similar_identical_and_substring 
[gw3] [ 89%] PASSED tests/test_text_similarity.py::test_is_similar_identical_and_substring 
tests/test_text_similarity.py::test_is_similar_rejects_unrelated 
[gw3] [ 90%] PASSED tests/test_text_similarity.py::test_is_similar_rejects_unrelated 
tests/test_text_similarity.py::test_is_similar_empty_is_never_similar 
[gw3] [ 90%] PASSED tests/test_text_similarity.py::test_is_similar_empty_is_never_similar 
tests/test_text_similarity.py::test_is_similar_threshold_is_configurable 
[gw2] [ 91%] PASSED tests/test_short_term_attribution.py::test_consolidate_group_unpacks_senders 
[gw3] [ 91%] PASSED tests/test_text_similarity.py::test_is_similar_threshold_is_configurable 
[gw1] [ 92%] PASSED tests/test_short_term_attribution.py::test_memory_candidates_drop_unknown_sender 
tests/test_text_similarity.py::test_merge_content_prefers_more_complete 
tests/test_source_kind.py::test_passive_messages_get_no_marker 
tests/test_source_kind.py::test_at_mention_messages_get_marker 
[gw3] [ 92%] PASSED tests/test_text_similarity.py::test_merge_content_prefers_more_complete 
tests/test_text_similarity.py::test_merge_content_handles_empty 
[gw3] [ 93%] PASSED tests/test_text_similarity.py::test_merge_content_handles_empty 
[gw2] [ 93%] PASSED tests/test_source_kind.py::test_passive_messages_get_no_marker 
tests/test_trace.py::test_record_trace_creates_table_and_inserts 
[gw1] [ 94%] PASSED tests/test_source_kind.py::test_at_mention_messages_get_marker 
tests/test_text_similarity.py::test_merge_content_joins_distinct 
tests/test_trace.py::test_record_trace_disabled 
[gw2] [ 94%] PASSED tests/test_text_similarity.py::test_merge_content_joins_distinct 
[gw1] [ 94%] PASSED tests/test_trace.py::test_record_trace_disabled 
[gw3] [ 95%] PASSED tests/test_trace.py::test_record_trace_creates_table_and_inserts 
tests/test_trace.py::test_dump_and_parse_helpers 
tests/test_trace.py::test_record_trace_no_memory_fields 
tests/test_trace.py::test_record_trace_truncates_long_fields 
[gw1] [ 95%] PASSED tests/test_trace.py::test_dump_and_parse_helpers 
tests/test_trace.py::test_memory_statistics_empty_and_missing_db 
[gw2] [ 96%] PASSED tests/test_trace.py::test_record_trace_no_memory_fields 
tests/test_trace.py::test_memory_statistics 
[gw1] [ 96%] PASSED tests/test_trace.py::test_memory_statistics_empty_and_missing_db 
[gw3] [ 97%] PASSED tests/test_trace.py::test_record_trace_truncates_long_fields 
tests/test_trace.py::test_prune_traces_no_db 
tests/test_trace.py::test_prune_traces 
[gw1] [ 97%] PASSED tests/test_trace.py::test_prune_traces_no_db 
[gw2] [ 98%] PASSED tests/test_trace.py::test_memory_statistics 
tests/test_trace.py::test_statistics_on_broken_rows 
[gw3] [ 98%] PASSED tests/test_trace.py::test_prune_traces 
[gw2] [ 99%] PASSED tests/test_trace.py::test_statistics_on_broken_rows 
[gw0] [ 99%] PASSED tests/test_lm_studio.py::test_generate_exhausts_retries_on_generic_error 
tests/test_memory_manager.py::test_high_value_candidate_becomes_confirmed_memory 
[gw0] [100%] PASSED tests/test_memory_manager.py::test_high_value_candidate_becomes_confirmed_memory 

==================================== ERRORS ====================================
___________________ ERROR collecting tests/test_benchmark.py ___________________
ImportError while importing test module '/home/runner/work/Stella_project/Stella_project/tests/test_benchmark.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_benchmark.py:9: in <module>
    import numpy as np
E   ModuleNotFoundError: No module named 'numpy'
=================================== FAILURES ===================================
_________________ test_pick_target_coldstart_avoids_last_topic _________________
[gw2] linux -- Python 3.12.13 /opt/hostedtoolcache/Python/3.12.13/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_pick_target_coldstart_avo0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fcb04471730>

    def test_pick_target_coldstart_avoids_last_topic(tmp_path, monkeypatch):
        """无候选 → mode=coldstart，且 topic 不等于 last_asked_topic。"""
        _setup_db(monkeypatch, tmp_path)
        monkeypatch.setattr(pt, "PROACTIVE_COLDSTART_TOPICS", ["游戏话题", "美食话题"])
        monkeypatch.setattr(proactive.time, "monotonic", _faketicks())
        c = proactive.ProactiveController()
        monkeypatch.setattr(pt, "get_proactive", lambda: c)
        c.record_message(1, 2001)
        proactive_state.record_at(1, 2001, topic="游戏话题")
    
        target = pick_target(1)
>       assert target is not None
E       assert None is not None

tests/test_proactive_target.py:225: AssertionError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.13-final-0 _______________

Name                                    Stmts   Miss Branch BrPart  Cover
-------------------------------------------------------------------------
config/__init__.py                          1      0      0      0   100%
config/settings.py                        179     15     18      7    89%
core/__init__.py                            0      0      0      0   100%
core/context.py                            27      0      0      0   100%
core/llm/__init__.py                        3      0      0      0   100%
core/llm/base.py                            5      0      0      0   100%
core/llm/lm_studio.py                      54      3     14      3    91%
core/pipeline.py                           81     19     18      6    75%
memory/__init__.py                          0      0      0      0   100%
memory/benchmark.py                       250    111     70      5    51%
memory/compressor.py                      154     10     38      7    90%
memory/consolidation_log.py                11      0      2      0   100%
memory/consolidation_prompt.py              6      0      0      0   100%
memory/consolidator.py                    424     70    144     25    82%
memory/db_cleaner.py                       98     20     32      6    78%
memory/embeddings.py                       65      5     16      4    89%
memory/memory_manager.py                  229     14     72      9    92%
memory/policy.py                          316     39    124     15    85%
memory/post_processors.py                  61     10     20      9    74%
memory/pre_processors.py                  196     75     72     18    56%
memory/proactive.py                       106     12     28      6    85%
memory/proactive_prompt.py                 12      0      2      0   100%
memory/proactive_state.py                  52      7      4      0    88%
memory/proactive_target.py                109     21     38      5    81%
memory/prompt_builder.py                  105     36     54     11    62%
memory/retrieval_v2.py                    185     31     50     12    80%
memory/retriever.py                       242     32    112     28    83%
memory/schema.py                          148     42     50      7    67%
memory/text_similarity.py                  33      1     16      1    96%
memory/trace.py                            89     11     20      1    89%
tests/conftest.py                          10      0      0      0   100%
tests/test_benchmark.py                    63     60     16      0     4%
tests/test_benchmark_and_log.py            71      1      0      0    99%
tests/test_bot_self_source.py              64      0      0      0   100%
tests/test_candidate_reinforcement.py     176      0      8      0   100%
tests/test_compressor.py                  110      1      0      0    99%
tests/test_consolidation_prompt.py         26      0      2      0   100%
tests/test_consolidator_core.py           163      0      0      0   100%
tests/test_context_tail.py                 58      2      2      0    97%
tests/test_cross_user_isolation.py         61      0      0      0   100%
tests/test_db_cleaner.py                   77      0      2      0   100%
tests/test_embeddings.py                   99      3      8      2    95%
tests/test_full_workflow.py               147      0      2      0   100%
tests/test_lm_studio.py                    77      1      2      0    99%
tests/test_memory_manager.py               51      0      0      0   100%
tests/test_memory_manager_fts_sync.py      66      0      0      0   100%
tests/test_memory_manager_v2.py            54      0      0      0   100%
tests/test_pipeline_compose.py             17      0      0      0   100%
tests/test_policy.py                       80      0      0      0   100%
tests/test_proactive_at_flow.py            41      0      0      0   100%
tests/test_proactive_prompt.py             34      0      8      0   100%
tests/test_proactive_rules.py             124      0      0      0   100%
tests/test_proactive_state.py              46      0      0      0   100%
tests/test_proactive_target.py            158      3      6      0    98%
tests/test_prompt_builder_v2.py            38      0      0      0   100%
tests/test_rag_switches.py                 68      0      0      0   100%
tests/test_retrieval_v2_and_schema.py     124      0      2      0   100%
tests/test_retriever.py                    78      0      0      0   100%
tests/test_short_term_attribution.py      107      0      0      0   100%
tests/test_source_kind.py                  25      0      0      0   100%
tests/test_text_similarity.py              32      0      0      0   100%
tests/test_trace.py                        99      0      0      0   100%
-------------------------------------------------------------------------
TOTAL                                    5685    655   1072    187    85%
=========================== short test summary info ============================
FAILED tests/test_proactive_target.py::test_pick_target_coldstart_avoids_last_topic - assert None is not None
ERROR tests/test_benchmark.py - ImportError while importing test module '/home/runner/work/Stella_project/Stella_project/tests/test_benchmark.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_benchmark.py:9: in <module>
    import numpy as np
E   ModuleNotFoundError: No module named 'numpy'
==================== 1 failed, 218 passed, 1 error in 7.64s ====================
Error: Process completed with exit code 1.

# coverage

Run coverage combine cov-*
  coverage combine cov-*
  shell: /usr/bin/bash -e {0}
  env:
    pythonLocation: /opt/hostedtoolcache/Python/3.11.15/x64
    PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.11.15/x64/lib/pkgconfig
    Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.15/x64
    Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.15/x64
    Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.15/x64
    LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.11.15/x64/lib
Couldn't combine from non-existent path 'cov-*'
Error: Process completed with exit code 1.