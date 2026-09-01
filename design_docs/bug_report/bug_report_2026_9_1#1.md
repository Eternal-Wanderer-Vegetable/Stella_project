Run pytest tests/ \
============================= test session starts ==============================
platform linux -- Python 3.10.21, pytest-9.1.1, pluggy-1.6.0 -- /opt/hostedtoolcache/Python/3.10.21/x64/bin/python
cachedir: .pytest_cache
rootdir: /home/runner/work/Stella_project/Stella_project
configfile: pyproject.toml
plugins: anyio-4.14.2, cov-7.1.0, timeout-2.4.0, xdist-3.8.0
timeout: 120.0s
timeout method: thread
timeout func_only: False
created: 4/4 workers
4 workers [622 items]

scheduling tests via LoadGroupScheduling

tests/capability/test_astrbot_adapter.py::test_derived_capability_has_no_examples_or_keywords 
tests/capability/test_astrbot_adapter.py::test_auto_capability_id_prefix 
tests/capability/test_astrbot_adapter.py::test_description_falls_back_to_tool_name 
tests/capability/test_astrbot_adapter.py::test_derives_capability_per_tool 
[gw3] [  0%] ERROR tests/capability/test_astrbot_adapter.py::test_derived_capability_has_no_examples_or_keywords 
[gw0] [  0%] ERROR tests/capability/test_astrbot_adapter.py::test_auto_capability_id_prefix 
tests/capability/test_astrbot_adapter.py::test_unclaimed_tools_still_derived_alongside_declarations 
tests/capability/test_astrbot_adapter.py::test_input_schema_copied_from_tool 
[gw1] [  0%] ERROR tests/capability/test_astrbot_adapter.py::test_derives_capability_per_tool 
[gw2] [  0%] ERROR tests/capability/test_astrbot_adapter.py::test_description_falls_back_to_tool_name 
tests/capability/test_astrbot_adapter.py::test_inactive_tools_are_skipped 
tests/capability/test_astrbot_adapter.py::test_declared_tool_is_not_derived 
[gw3] [  0%] ERROR tests/capability/test_astrbot_adapter.py::test_unclaimed_tools_still_derived_alongside_declarations 
tests/capability/test_astrbot_adapter.py::test_sync_is_idempotent 
[gw1] [  0%] ERROR tests/capability/test_astrbot_adapter.py::test_inactive_tools_are_skipped 
[gw0] [  1%] ERROR tests/capability/test_astrbot_adapter.py::test_input_schema_copied_from_tool 
[gw2] [  1%] ERROR tests/capability/test_astrbot_adapter.py::test_declared_tool_is_not_derived 
tests/capability/test_astrbot_adapter.py::test_sync_picks_up_newly_added_tools 
tests/capability/test_astrbot_adapter.py::test_bootstrap_lets_declaration_claim_the_tool 
tests/capability/test_astrbot_adapter.py::test_bootstrap_with_no_declarations_is_all_auto 
[gw3] [  1%] ERROR tests/capability/test_astrbot_adapter.py::test_sync_is_idempotent 
tests/capability/test_astrbot_adapter.py::test_derived_capability_is_registered_but_not_routable 
[gw1] [  1%] ERROR tests/capability/test_astrbot_adapter.py::test_bootstrap_lets_declaration_claim_the_tool 
[gw2] [  1%] ERROR tests/capability/test_astrbot_adapter.py::test_bootstrap_with_no_declarations_is_all_auto 
[gw0] [  1%] ERROR tests/capability/test_astrbot_adapter.py::test_sync_picks_up_newly_added_tools 
tests/capability/test_astrbot_adapter.py::test_auto_route_policy_reads_settings 
tests/capability/test_astrbot_adapter.py::test_bootstrap_reports_routable_count 
tests/capability/test_astrbot_adapter.py::test_auto_capabilities_route_when_opted_in 
[gw3] [  2%] ERROR tests/capability/test_astrbot_adapter.py::test_derived_capability_is_registered_but_not_routable 
[gw2] [  2%] ERROR tests/capability/test_astrbot_adapter.py::test_bootstrap_reports_routable_count 
tests/capability/test_capability_hooks.py::test_build_tool_tasks_uses_user_message_as_objective 
tests/capability/test_capability_hooks.py::test_build_tool_tasks_one_per_capability 
[gw1] [  2%] ERROR tests/capability/test_astrbot_adapter.py::test_auto_route_policy_reads_settings 
tests/capability/test_capability_hooks.py::test_build_tool_tasks_empty_route 
[gw0] [  2%] ERROR tests/capability/test_astrbot_adapter.py::test_auto_capabilities_route_when_opted_in 
tests/capability/test_capability_hooks.py::test_memory_runs_when_gate_disabled 
[gw2] [  2%] ERROR tests/capability/test_capability_hooks.py::test_build_tool_tasks_one_per_capability 
[gw1] [  2%] ERROR tests/capability/test_capability_hooks.py::test_build_tool_tasks_empty_route 
tests/capability/test_capability_hooks.py::test_memory_runs_when_gate_enabled_and_route_wants_it 
[gw3] [  3%] ERROR tests/capability/test_capability_hooks.py::test_build_tool_tasks_uses_user_message_as_objective 
tests/capability/test_capability_hooks.py::test_route_is_stored_on_context 
tests/capability/test_capability_hooks.py::test_memory_skipped_when_gate_enabled 
[gw0] [  3%] ERROR tests/capability/test_capability_hooks.py::test_memory_runs_when_gate_disabled 
tests/capability/test_capability_hooks.py::test_intent_and_trigger_are_passed_to_router 
[gw2] [  3%] ERROR tests/capability/test_capability_hooks.py::test_memory_runs_when_gate_enabled_and_route_wants_it 
[gw1] [  3%] ERROR tests/capability/test_capability_hooks.py::test_route_is_stored_on_context 
tests/capability/test_capability_hooks.py::test_comes_runs_and_fills_summaries 
[gw3] [  3%] ERROR tests/capability/test_capability_hooks.py::test_memory_skipped_when_gate_enabled 
tests/capability/test_capability_hooks.py::test_comes_skipped_without_platform_handles 
tests/capability/test_capability_hooks.py::test_comes_skipped_when_disabled 
[gw0] [  3%] ERROR tests/capability/test_capability_hooks.py::test_intent_and_trigger_are_passed_to_router 
tests/capability/test_capability_hooks.py::test_comes_skipped_when_compat_disabled 
[gw1] [  4%] ERROR tests/capability/test_capability_hooks.py::test_comes_skipped_without_platform_handles 
tests/capability/test_capability_hooks.py::test_both_branches_run_concurrently 
[gw2] [  4%] ERROR tests/capability/test_capability_hooks.py::test_comes_runs_and_fills_summaries 
[gw3] [  4%] ERROR tests/capability/test_capability_hooks.py::test_comes_skipped_when_disabled 
tests/capability/test_capability_hooks.py::test_failed_results_do_not_reach_the_prompt 
tests/capability/test_capability_hooks.py::test_memory_failure_does_not_kill_comes 
[gw0] [  4%] ERROR tests/capability/test_capability_hooks.py::test_comes_skipped_when_compat_disabled 
tests/capability/test_capability_hooks.py::test_comes_failure_does_not_kill_memory 
[gw3] [  4%] ERROR tests/capability/test_capability_hooks.py::test_memory_failure_does_not_kill_comes 
[gw0] [  4%] ERROR tests/capability/test_capability_hooks.py::test_comes_failure_does_not_kill_memory 
tests/capability/test_capability_hooks.py::test_register_uses_priority_below_build_context 
tests/capability/test_capability_hooks.py::test_registry_singleton_is_used_by_default 
[gw1] [  4%] ERROR tests/capability/test_capability_hooks.py::test_both_branches_run_concurrently 
[gw2] [  5%] ERROR tests/capability/test_capability_hooks.py::test_failed_results_do_not_reach_the_prompt 
tests/capability/test_capability_hooks.py::test_router_entry_failure_degrades_to_memory 
tests/capability/test_capability_hooks.py::test_no_jobs_returns_context_unchanged 
[gw2] [  5%] ERROR tests/capability/test_capability_hooks.py::test_no_jobs_returns_context_unchanged 
[gw1] [  5%] ERROR tests/capability/test_capability_hooks.py::test_router_entry_failure_degrades_to_memory 
[gw3] [  5%] ERROR tests/capability/test_capability_hooks.py::test_register_uses_priority_below_build_context 
tests/capability/test_capability_loader.py::test_provider_priority_falls_back_on_bad_value 
tests/capability/test_capability_loader.py::test_skips_providers_without_tool_name 
[gw0] [  5%] ERROR tests/capability/test_capability_hooks.py::test_registry_singleton_is_used_by_default 
tests/capability/test_capability_loader.py::test_loads_capability_with_string_providers 
tests/capability/test_capability_loader.py::test_loads_table_providers_with_priority 
[gw2] [  5%] ERROR tests/capability/test_capability_loader.py::test_provider_priority_falls_back_on_bad_value 
tests/capability/test_capability_loader.py::test_skips_capability_without_id 
[gw1] [  6%] ERROR tests/capability/test_capability_loader.py::test_skips_providers_without_tool_name 
[gw3] [  6%] ERROR tests/capability/test_capability_loader.py::test_loads_capability_with_string_providers 
[gw0] [  6%] ERROR tests/capability/test_capability_loader.py::test_loads_table_providers_with_priority 
tests/capability/test_capability_loader.py::test_accepts_single_table_form 
tests/capability/test_capability_loader.py::test_missing_capability_section_is_skipped 
tests/capability/test_capability_loader.py::test_broken_toml_is_skipped_not_raised 
[gw0] [  6%] ERROR tests/capability/test_capability_loader.py::test_missing_capability_section_is_skipped 
[gw3] [  6%] ERROR tests/capability/test_capability_loader.py::test_broken_toml_is_skipped_not_raised 
tests/capability/test_capability_loader.py::test_empty_directory_returns_zero 
tests/capability/test_capability_loader.py::test_missing_directory_returns_zero 
[gw2] [  6%] ERROR tests/capability/test_capability_loader.py::test_skips_capability_without_id 
tests/capability/test_capability_loader.py::test_non_list_capability_section_is_skipped 
[gw1] [  7%] ERROR tests/capability/test_capability_loader.py::test_accepts_single_table_form 
tests/capability/test_capability_loader.py::test_load_directory_merges_all_files_deterministically 
[gw2] [  7%] ERROR tests/capability/test_capability_loader.py::test_non_list_capability_section_is_skipped 
tests/capability/test_comes_executor.py::test_resolve_tools_skips_inactive_tools 
[gw1] [  7%] ERROR tests/capability/test_capability_loader.py::test_load_directory_merges_all_files_deterministically 
[gw3] [  7%] ERROR tests/capability/test_capability_loader.py::test_missing_directory_returns_zero 
tests/capability/test_comes_executor.py::test_resolve_tools_reports_unsupported_kind 
tests/capability/test_capability_loader.py::test_input_schema_is_kept_only_when_dict 
[gw0] [  7%] ERROR tests/capability/test_capability_loader.py::test_empty_directory_returns_zero 
tests/capability/test_comes_executor.py::test_resolve_tools_reports_missing_plugins 
[gw2] [  7%] ERROR tests/capability/test_comes_executor.py::test_resolve_tools_skips_inactive_tools 
[gw1] [  8%] ERROR tests/capability/test_comes_executor.py::test_resolve_tools_reports_unsupported_kind 
tests/capability/test_comes_executor.py::test_can_direct_call_only_for_single_no_arg_tool 
tests/capability/test_comes_executor.py::test_disabled_comes_fails_fast 
[gw3] [  8%] ERROR tests/capability/test_capability_loader.py::test_input_schema_is_kept_only_when_dict 
tests/capability/test_comes_executor.py::test_missing_event_fails_fast 
[gw0] [  8%] ERROR tests/capability/test_comes_executor.py::test_resolve_tools_reports_missing_plugins 
tests/capability/test_comes_executor.py::test_unknown_capability_fails 
[gw2] [  8%] ERROR tests/capability/test_comes_executor.py::test_can_direct_call_only_for_single_no_arg_tool 
[gw1] [  8%] ERROR tests/capability/test_comes_executor.py::test_disabled_comes_fails_fast 
tests/capability/test_comes_executor.py::test_capability_without_provider_fails 
tests/capability/test_comes_executor.py::test_all_tools_unavailable_fails 
[gw3] [  8%] ERROR tests/capability/test_comes_executor.py::test_missing_event_fails_fast 
tests/capability/test_comes_executor.py::test_direct_call_skips_the_model 
[gw0] [  9%] ERROR tests/capability/test_comes_executor.py::test_unknown_capability_fails 
tests/capability/test_comes_executor.py::test_direct_call_can_be_disabled 
[gw1] [  9%] ERROR tests/capability/test_comes_executor.py::test_all_tools_unavailable_fails 
tests/capability/test_comes_executor.py::test_only_scoped_tools_reach_the_model 
[gw2] [  9%] ERROR tests/capability/test_comes_executor.py::test_capability_without_provider_fails 
tests/capability/test_comes_executor.py::test_direct_call_passes_task_input_as_args 
[gw3] [  9%] ERROR tests/capability/test_comes_executor.py::test_direct_call_skips_the_model 
[gw0] [  9%] ERROR tests/capability/test_comes_executor.py::test_direct_call_can_be_disabled 
tests/capability/test_comes_executor.py::test_stella_persona_and_chat_context_never_reach_comes 
tests/capability/test_comes_executor.py::test_objective_carries_known_slots 
[gw1] [  9%] ERROR tests/capability/test_comes_executor.py::test_only_scoped_tools_reach_the_model 
[gw2] [  9%] ERROR tests/capability/test_comes_executor.py::test_direct_call_passes_task_input_as_args 
tests/capability/test_comes_executor.py::test_agent_completion_becomes_summary 
tests/capability/test_comes_executor.py::test_no_tool_called_is_failed 
[gw3] [ 10%] ERROR tests/capability/test_comes_executor.py::test_stella_persona_and_chat_context_never_reach_comes 
[gw0] [ 10%] ERROR tests/capability/test_comes_executor.py::test_objective_carries_known_slots 
tests/capability/test_comes_executor.py::test_partial_when_some_tools_fail 
tests/capability/test_comes_executor.py::test_tool_error_is_failed 
[gw1] [ 10%] ERROR tests/capability/test_comes_executor.py::test_agent_completion_becomes_summary 
[gw2] [ 10%] ERROR tests/capability/test_comes_executor.py::test_no_tool_called_is_failed 
tests/capability/test_comes_executor.py::test_timeout_is_failed_not_raised 
tests/capability/test_comes_executor.py::test_llm_disabled_is_failed_not_raised 
[gw3] [ 10%] ERROR tests/capability/test_comes_executor.py::test_tool_error_is_failed 
tests/capability/test_comes_executor.py::test_execute_all_empty_returns_empty 
[gw0] [ 10%] ERROR tests/capability/test_comes_executor.py::test_partial_when_some_tools_fail 
tests/capability/test_comes_executor.py::test_execute_all_returns_in_input_order 
[gw3] [ 11%] ERROR tests/capability/test_comes_executor.py::test_execute_all_empty_returns_empty 
tests/capability/test_comes_executor.py::test_success_clears_recorded_failures 
[gw0] [ 11%] ERROR tests/capability/test_comes_executor.py::test_execute_all_returns_in_input_order 
tests/capability/test_comes_executor.py::test_uncalled_providers_are_not_charged 
[gw2] [ 11%] ERROR tests/capability/test_comes_executor.py::test_timeout_is_failed_not_raised 
[gw1] [ 11%] ERROR tests/capability/test_comes_executor.py::test_llm_disabled_is_failed_not_raised 
tests/capability/test_comes_executor.py::test_failure_is_recorded_on_the_provider 
tests/capability/test_comes_executor.py::test_execute_all_survives_a_broken_task 
[gw2] [ 11%] ERROR tests/capability/test_comes_executor.py::test_execute_all_survives_a_broken_task 
[gw1] [ 11%] ERROR tests/capability/test_comes_executor.py::test_failure_is_recorded_on_the_provider 
tests/capability/test_comes_summarizer.py::test_is_no_return_matches_internal_marker 
tests/capability/test_comes_summarizer.py::test_truncate_adds_ellipsis_only_when_needed 
[gw3] [ 12%] ERROR tests/capability/test_comes_executor.py::test_success_clears_recorded_failures 
tests/capability/test_comes_executor.py::test_backed_off_provider_is_skipped_next_time 
[gw0] [ 12%] ERROR tests/capability/test_comes_executor.py::test_uncalled_providers_are_not_charged 
tests/capability/test_comes_summarizer.py::test_is_error_matches_execute_tool_prefix 
[gw2] [ 12%] ERROR tests/capability/test_comes_summarizer.py::test_is_no_return_matches_internal_marker 
[gw1] [ 12%] ERROR tests/capability/test_comes_summarizer.py::test_truncate_adds_ellipsis_only_when_needed 
tests/capability/test_comes_summarizer.py::test_truncate_unlimited_when_limit_non_positive 
tests/capability/test_comes_summarizer.py::test_single_output_has_no_tool_name_prefix 
[gw3] [ 12%] ERROR tests/capability/test_comes_executor.py::test_backed_off_provider_is_skipped_next_time 
tests/capability/test_comes_summarizer.py::test_multiple_outputs_are_listed 
[gw0] [ 12%] ERROR tests/capability/test_comes_summarizer.py::test_is_error_matches_execute_tool_prefix 
tests/capability/test_comes_summarizer.py::test_errors_and_no_return_are_dropped 
[gw3] [ 13%] ERROR tests/capability/test_comes_summarizer.py::test_multiple_outputs_are_listed 
tests/capability/test_comes_summarizer.py::test_completion_text_wins_when_present 
[gw0] [ 13%] ERROR tests/capability/test_comes_summarizer.py::test_errors_and_no_return_are_dropped 
tests/capability/test_comes_summarizer.py::test_falls_back_to_outputs_when_completion_empty 
[gw1] [ 13%] ERROR tests/capability/test_comes_summarizer.py::test_single_output_has_no_tool_name_prefix 
[gw2] [ 13%] ERROR tests/capability/test_comes_summarizer.py::test_truncate_unlimited_when_limit_non_positive 
tests/capability/test_comes_summarizer.py::test_budget_is_split_across_multiple_outputs 
tests/capability/test_comes_summarizer.py::test_all_unusable_returns_empty 
[gw2] [ 13%] ERROR tests/capability/test_comes_summarizer.py::test_all_unusable_returns_empty 
[gw1] [ 13%] ERROR tests/capability/test_comes_summarizer.py::test_budget_is_split_across_multiple_outputs 
tests/capability/test_comes_summarizer.py::test_everything_empty_returns_empty 
tests/capability/test_comes_summarizer.py::test_stringify_handles_non_strings 
[gw3] [ 13%] ERROR tests/capability/test_comes_summarizer.py::test_completion_text_wins_when_present 
tests/capability/test_comes_summarizer.py::test_completion_echoing_internal_marker_is_ignored 
[gw0] [ 14%] ERROR tests/capability/test_comes_summarizer.py::test_falls_back_to_outputs_when_completion_empty 
tests/capability/test_comes_summarizer.py::test_completion_is_truncated_to_budget 
[gw2] [ 14%] ERROR tests/capability/test_comes_summarizer.py::test_stringify_handles_non_strings 
[gw1] [ 14%] ERROR tests/capability/test_comes_summarizer.py::test_everything_empty_returns_empty 
tests/capability/test_plugin_capability_tiers.py::test_declaration_filename_must_be_exact 
tests/capability/test_plugin_capability_tiers.py::test_plugin_declaration_is_loaded_and_tagged 
[gw3] [ 14%] ERROR tests/capability/test_comes_summarizer.py::test_completion_echoing_internal_marker_is_ignored 
tests/capability/test_plugin_capability_tiers.py::test_reviewed_false_blocks_the_whole_file 
[gw0] [ 14%] ERROR tests/capability/test_comes_summarizer.py::test_completion_is_truncated_to_budget 
tests/capability/test_plugin_capability_tiers.py::test_reviewed_true_is_loaded 
[gw1] [ 14%] ERROR tests/capability/test_plugin_capability_tiers.py::test_plugin_declaration_is_loaded_and_tagged 
tests/capability/test_plugin_capability_tiers.py::test_failed_plugin_declaration_is_not_loaded 
[gw3] [ 15%] ERROR tests/capability/test_plugin_capability_tiers.py::test_reviewed_false_blocks_the_whole_file 
tests/capability/test_plugin_capability_tiers.py::test_deactivated_plugin_declaration_is_not_loaded 
[gw0] [ 15%] ERROR tests/capability/test_plugin_capability_tiers.py::test_reviewed_true_is_loaded 
tests/capability/test_plugin_capability_tiers.py::test_broken_plugin_toml_does_not_stop_the_tier 
[gw2] [ 15%] ERROR tests/capability/test_plugin_capability_tiers.py::test_declaration_filename_must_be_exact 
tests/capability/test_plugin_capability_tiers.py::test_missing_reviewed_key_is_treated_as_reviewed 
[gw1] [ 15%] ERROR tests/capability/test_plugin_capability_tiers.py::test_failed_plugin_declaration_is_not_loaded 
[gw2] [ 15%] ERROR tests/capability/test_plugin_capability_tiers.py::test_missing_reviewed_key_is_treated_as_reviewed 
tests/capability/test_plugin_capability_tiers.py::test_switch_off_skips_the_whole_plugin_tier 
tests/capability/test_plugin_capability_tiers.py::test_user_override_under_a_different_id_still_shadows_the_plugin 
[gw3] [ 15%] ERROR tests/capability/test_plugin_capability_tiers.py::test_deactivated_plugin_declaration_is_not_loaded 
[gw0] [ 16%] ERROR tests/capability/test_plugin_capability_tiers.py::test_broken_plugin_toml_does_not_stop_the_tier 
tests/capability/test_plugin_capability_tiers.py::test_user_tier_wins_over_factory_and_plugin 
tests/capability/test_plugin_capability_tiers.py::test_plugin_wins_when_no_config_tier_declares_the_tool 
[gw1] [ 16%] ERROR tests/capability/test_plugin_capability_tiers.py::test_switch_off_skips_the_whole_plugin_tier 
[gw2] [ 16%] ERROR tests/capability/test_plugin_capability_tiers.py::test_user_override_under_a_different_id_still_shadows_the_plugin 
tests/capability/test_plugin_capability_tiers.py::test_factory_tier_is_not_shadowed_by_a_user_file 
tests/capability/test_plugin_capability_tiers.py::test_identical_config_dirs_are_read_once 
[gw3] [ 16%] ERROR tests/capability/test_plugin_capability_tiers.py::test_user_tier_wins_over_factory_and_plugin 
[gw0] [ 16%] ERROR tests/capability/test_plugin_capability_tiers.py::test_plugin_wins_when_no_config_tier_declares_the_tool 
tests/capability/test_plugin_capability_tiers.py::test_config_dirs_are_user_first 
tests/capability/test_registry.py::test_prototype_texts_includes_examples_and_description 
[gw1] [ 16%] ERROR tests/capability/test_plugin_capability_tiers.py::test_factory_tier_is_not_shadowed_by_a_user_file 
[gw2] [ 17%] ERROR tests/capability/test_plugin_capability_tiers.py::test_identical_config_dirs_are_read_once 
tests/capability/test_registry.py::test_prototype_texts_drops_blank_entries 
tests/capability/test_registry.py::test_enabled_providers_sorted_by_priority_desc 
[gw3] [ 17%] ERROR tests/capability/test_plugin_capability_tiers.py::test_config_dirs_are_user_first 
[gw0] [ 17%] ERROR tests/capability/test_registry.py::test_prototype_texts_includes_examples_and_description 
tests/capability/test_registry.py::test_enabled_providers_is_stable_within_same_priority 
tests/capability/test_registry.py::test_disabled_providers_are_excluded 
[gw3] [ 17%] ERROR tests/capability/test_registry.py::test_enabled_providers_is_stable_within_same_priority 
[gw0] [ 17%] ERROR tests/capability/test_registry.py::test_disabled_providers_are_excluded 
tests/capability/test_registry.py::test_register_fills_empty_fields_from_later_registration 
tests/capability/test_registry.py::test_register_does_not_duplicate_examples 
[gw2] [ 17%] ERROR tests/capability/test_registry.py::test_enabled_providers_sorted_by_priority_desc 
[gw1] [ 18%] ERROR tests/capability/test_registry.py::test_prototype_texts_drops_blank_entries 
tests/capability/test_registry.py::test_register_merges_instead_of_overwriting 
tests/capability/test_registry.py::test_is_auto_detects_derived_capabilities 
[gw2] [ 18%] ERROR tests/capability/test_registry.py::test_register_merges_instead_of_overwriting 
[gw1] [ 18%] ERROR tests/capability/test_registry.py::test_is_auto_detects_derived_capabilities 
tests/capability/test_registry.py::test_add_provider_rebinds_capability_id 
tests/capability/test_registry.py::test_tool_claim_is_first_come_first_served 
[gw3] [ 18%] ERROR tests/capability/test_registry.py::test_register_fills_empty_fields_from_later_registration 
[gw0] [ 18%] ERROR tests/capability/test_registry.py::test_register_does_not_duplicate_examples 
tests/capability/test_registry.py::test_add_provider_rejects_duplicate_provider_id 
tests/capability/test_registry.py::test_add_provider_to_unknown_capability_returns_false 
[gw1] [ 18%] ERROR tests/capability/test_registry.py::test_tool_claim_is_first_come_first_served 
[gw2] [ 18%] ERROR tests/capability/test_registry.py::test_add_provider_rebinds_capability_id 
tests/capability/test_registry.py::test_routable_requires_provider_and_prototype 
tests/capability/test_registry.py::test_claimed_by_returns_none_for_unknown_tool 
[gw0] [ 19%] ERROR tests/capability/test_registry.py::test_add_provider_to_unknown_capability_returns_false 
[gw3] [ 19%] ERROR tests/capability/test_registry.py::test_add_provider_rejects_duplicate_provider_id 
tests/capability/test_registry.py::test_register_merge_lets_declaration_win_route_enabled 
tests/capability/test_registry.py::test_routable_excludes_route_disabled 
[gw0] [ 19%] ERROR tests/capability/test_registry.py::test_register_merge_lets_declaration_win_route_enabled 
[gw3] [ 19%] ERROR tests/capability/test_registry.py::test_routable_excludes_route_disabled 
tests/capability/test_registry.py::test_all_and_ids_are_sorted 
tests/capability/test_registry.py::test_clear_resets_claims_too 
[gw1] [ 19%] ERROR tests/capability/test_registry.py::test_routable_requires_provider_and_prototype 
[gw2] [ 19%] ERROR tests/capability/test_registry.py::test_claimed_by_returns_none_for_unknown_tool 
tests/capability/test_registry.py::test_register_merge_keeps_disabled_on_idempotent_resync 
tests/capability/test_registry.py::test_version_bumps_on_every_mutation 
[gw1] [ 20%] ERROR tests/capability/test_registry.py::test_register_merge_keeps_disabled_on_idempotent_resync 
tests/capability/test_registry.py::test_unregister_releases_providers_added_afterwards 
[gw2] [ 20%] ERROR tests/capability/test_registry.py::test_version_bumps_on_every_mutation 
tests/capability/test_registry.py::test_unregister_unknown_returns_false_and_keeps_version 
[gw0] [ 20%] ERROR tests/capability/test_registry.py::test_all_and_ids_are_sorted 
[gw3] [ 20%] ERROR tests/capability/test_registry.py::test_clear_resets_claims_too 
tests/capability/test_registry.py::test_unregister_releases_claimed_tools 
tests/capability/test_registry.py::test_unregister_only_releases_its_own_tools 
[gw1] [ 20%] ERROR tests/capability/test_registry.py::test_unregister_releases_providers_added_afterwards 
tests/capability/test_registry.py::test_release_tool_frees_a_single_claim 
[gw2] [ 20%] ERROR tests/capability/test_registry.py::test_unregister_unknown_returns_false_and_keeps_version 
tests/capability/test_registry.py::test_module_singleton_is_shared_across_import_paths 
[gw0] [ 21%] ERROR tests/capability/test_registry.py::test_unregister_releases_claimed_tools 
tests/capability/test_registry.py::test_package_does_not_shadow_registry_submodule 
[gw3] [ 21%] ERROR tests/capability/test_registry.py::test_unregister_only_releases_its_own_tools 
tests/capability/test_router_benchmark.py::test_builtin_cases_pass_rules_only 
[gw1] [ 21%] ERROR tests/capability/test_registry.py::test_release_tool_frees_a_single_claim 
tests/capability/test_router_benchmark.py::test_builtin_cases_cover_the_known_traps 
[gw0] [ 21%] ERROR tests/capability/test_registry.py::test_package_does_not_shadow_registry_submodule 
tests/capability/test_router_benchmark.py::test_gate_safe_ignores_low_cost_errors 
[gw3] [ 21%] ERROR tests/capability/test_router_benchmark.py::test_builtin_cases_pass_rules_only 
tests/capability/test_router_benchmark.py::test_capability_miss_detected 
[gw2] [ 21%] ERROR tests/capability/test_registry.py::test_module_singleton_is_shared_across_import_paths 
tests/capability/test_router_benchmark.py::test_gate_safe_requires_zero_memory_false_negative 
[gw1] [ 22%] ERROR tests/capability/test_router_benchmark.py::test_builtin_cases_cover_the_known_traps 
tests/capability/test_router_benchmark.py::test_capability_not_checked_when_unspecified 
[gw2] [ 22%] ERROR tests/capability/test_router_benchmark.py::test_gate_safe_requires_zero_memory_false_negative 
tests/capability/test_router_benchmark.py::test_render_on_clean_report 
[gw0] [ 22%] ERROR tests/capability/test_router_benchmark.py::test_gate_safe_ignores_low_cost_errors 
tests/capability/test_router_benchmark.py::test_by_level_counts_decisions 
[gw3] [ 22%] ERROR tests/capability/test_router_benchmark.py::test_capability_miss_detected 
tests/capability/test_router_benchmark.py::test_render_lists_high_cost_failures 
[gw1] [ 22%] ERROR tests/capability/test_router_benchmark.py::test_capability_not_checked_when_unspecified 
tests/capability/test_router_benchmark.py::test_load_cases_from_file 
[gw2] [ 22%] ERROR tests/capability/test_router_benchmark.py::test_render_on_clean_report 
tests/capability/test_router_benchmark.py::test_load_cases_rejects_non_array 
[gw0] [ 22%] ERROR tests/capability/test_router_benchmark.py::test_by_level_counts_decisions 
tests/capability/test_router_benchmark.py::test_load_cases_falls_back_to_builtin 
[gw3] [ 23%] ERROR tests/capability/test_router_benchmark.py::test_render_lists_high_cost_failures 
tests/capability/test_router_benchmark.py::test_load_cases_merges_builtin_with_files 
[gw1] [ 23%] ERROR tests/capability/test_router_benchmark.py::test_load_cases_from_file 
tests/capability/test_router_benchmark.py::test_explicit_path_does_not_merge_builtin 
[gw2] [ 23%] ERROR tests/capability/test_router_benchmark.py::test_load_cases_rejects_non_array 
tests/capability/test_router_benchmark.py::test_shipped_acg_cases_are_wellformed 
[gw0] [ 23%] ERROR tests/capability/test_router_benchmark.py::test_load_cases_falls_back_to_builtin 
tests/capability/test_router_benchmark.py::test_provider_available_by_default 
[gw3] [ 23%] ERROR tests/capability/test_router_benchmark.py::test_load_cases_merges_builtin_with_files 
tests/capability/test_router_benchmark.py::test_manual_disable_beats_health 
[gw0] [ 23%] ERROR tests/capability/test_router_benchmark.py::test_provider_available_by_default 
tests/capability/test_router_benchmark.py::test_success_clears_failures_and_backoff 
[gw3] [ 24%] ERROR tests/capability/test_router_benchmark.py::test_manual_disable_beats_health 
[gw1] [ 24%] ERROR tests/capability/test_router_benchmark.py::test_explicit_path_does_not_merge_builtin 
tests/capability/test_router_benchmark.py::test_threshold_zero_disables_backoff 
tests/capability/test_router_benchmark.py::test_backoff_triggers_at_threshold 
[gw2] [ 24%] ERROR tests/capability/test_router_benchmark.py::test_shipped_acg_cases_are_wellformed 
tests/capability/test_router_benchmark.py::test_backoff_is_a_time_window_not_permanent 
[gw1] [ 24%] ERROR tests/capability/test_router_benchmark.py::test_backoff_triggers_at_threshold 
tests/capability/test_router_benchmark.py::test_repr_shows_backoff_state 
[gw2] [ 24%] ERROR tests/capability/test_router_benchmark.py::test_backoff_is_a_time_window_not_permanent 
tests/capability/test_router_cascade.py::test_route_to_dict_is_flat_and_readable 
[gw0] [ 24%] ERROR tests/capability/test_router_benchmark.py::test_success_clears_failures_and_backoff 
tests/capability/test_router_benchmark.py::test_backed_off_provider_excluded_from_selection 
[gw3] [ 25%] ERROR tests/capability/test_router_benchmark.py::test_threshold_zero_disables_backoff 
tests/capability/test_router_cascade.py::test_default_route_is_conservative 
[gw1] [ 25%] ERROR tests/capability/test_router_benchmark.py::test_repr_shows_backoff_state 
tests/capability/test_router_cascade.py::test_route_repr_lists_active_labels 
[gw2] [ 25%] ERROR tests/capability/test_router_cascade.py::test_route_to_dict_is_flat_and_readable 
tests/capability/test_router_cascade.py::test_top_score_survives_capability_filtering 
[gw0] [ 25%] ERROR tests/capability/test_router_benchmark.py::test_backed_off_provider_excluded_from_selection 
tests/capability/test_router_cascade.py::test_parse_verdict_extracts_json_from_noise 
[gw3] [ 25%] ERROR tests/capability/test_router_cascade.py::test_default_route_is_conservative 
tests/capability/test_router_cascade.py::test_parse_verdict_accepts_string_booleans 
[gw0] [ 25%] ERROR tests/capability/test_router_cascade.py::test_parse_verdict_extracts_json_from_noise 
tests/capability/test_router_cascade.py::test_fallback_disabled_returns_none 
[gw3] [ 26%] ERROR tests/capability/test_router_cascade.py::test_parse_verdict_accepts_string_booleans 
tests/capability/test_router_cascade.py::test_fallback_picks_capability 
[gw1] [ 26%] ERROR tests/capability/test_router_cascade.py::test_route_repr_lists_active_labels 
tests/capability/test_router_cascade.py::test_parse_verdict_returns_none_on_garbage 
[gw2] [ 26%] ERROR tests/capability/test_router_cascade.py::test_top_score_survives_capability_filtering 
tests/capability/test_router_cascade.py::test_build_catalog_omits_examples 
[gw1] [ 26%] ERROR tests/capability/test_router_cascade.py::test_parse_verdict_returns_none_on_garbage 
tests/capability/test_router_cascade.py::test_fallback_returns_none_on_unparseable_output 
[gw2] [ 26%] ERROR tests/capability/test_router_cascade.py::test_build_catalog_omits_examples 
tests/capability/test_router_cascade.py::test_fallback_returns_none_when_catalog_empty 
[gw0] [ 26%] ERROR tests/capability/test_router_cascade.py::test_fallback_disabled_returns_none 
tests/capability/test_router_cascade.py::test_fallback_rejects_hallucinated_capability 
[gw3] [ 27%] ERROR tests/capability/test_router_cascade.py::test_fallback_picks_capability 
tests/capability/test_router_cascade.py::test_fallback_returns_none_on_backend_failure 
[gw1] [ 27%] ERROR tests/capability/test_router_cascade.py::test_fallback_returns_none_on_unparseable_output 
tests/capability/test_router_cascade.py::test_router_disabled_returns_default 
[gw2] [ 27%] ERROR tests/capability/test_router_cascade.py::test_fallback_returns_none_when_catalog_empty 
tests/capability/test_router_cascade.py::test_instruction_intent_skips_routing 
[gw0] [ 27%] ERROR tests/capability/test_router_cascade.py::test_fallback_rejects_hallucinated_capability 
tests/capability/test_router_cascade.py::test_level0_short_circuits_before_embedding 
[gw3] [ 27%] ERROR tests/capability/test_router_cascade.py::test_fallback_returns_none_on_backend_failure 
tests/capability/test_router_cascade.py::test_level1_runs_when_rules_defer 
[gw1] [ 27%] ERROR tests/capability/test_router_cascade.py::test_router_disabled_returns_default 
tests/capability/test_router_cascade.py::test_semantic_unavailable_degrades 
[gw0] [ 27%] ERROR tests/capability/test_router_cascade.py::test_level0_short_circuits_before_embedding 
[gw3] [ 28%] ERROR tests/capability/test_router_cascade.py::test_level1_runs_when_rules_defer 
tests/capability/test_router_cascade.py::test_semantic_disabled_degrades 
tests/capability/test_router_cascade.py::test_level2_only_triggers_inside_uncertain_band 
[gw2] [ 28%] ERROR tests/capability/test_router_cascade.py::test_instruction_intent_skips_routing 
tests/capability/test_router_cascade.py::test_empty_registry_degrades 
[gw1] [ 28%] ERROR tests/capability/test_router_cascade.py::test_semantic_unavailable_degrades 
tests/capability/test_router_cascade.py::test_level2_failure_keeps_semantic_conclusion 
[gw2] [ 28%] ERROR tests/capability/test_router_cascade.py::test_empty_registry_degrades 
tests/capability/test_router_cascade.py::test_elapsed_is_recorded 
[gw0] [ 28%] ERROR tests/capability/test_router_cascade.py::test_semantic_disabled_degrades 
tests/capability/test_router_cascade.py::test_timeout_degrades 
[gw3] [ 28%] ERROR tests/capability/test_router_cascade.py::test_level2_only_triggers_inside_uncertain_band 
tests/capability/test_router_cascade.py::test_exception_degrades_and_never_raises 
[gw1] [ 29%] ERROR tests/capability/test_router_cascade.py::test_level2_failure_keeps_semantic_conclusion 
tests/capability/test_router_rules.py::test_tool_and_memory_intent_markers 
[gw2] [ 29%] ERROR tests/capability/test_router_cascade.py::test_elapsed_is_recorded 
tests/capability/test_router_rules.py::test_match_capabilities_hits_declared_keyword 
[gw0] [ 29%] ERROR tests/capability/test_router_cascade.py::test_timeout_degrades 
tests/capability/test_router_rules.py::test_match_capabilities_ignores_words_only_in_examples 
[gw3] [ 29%] ERROR tests/capability/test_router_cascade.py::test_exception_degrades_and_never_raises 
tests/capability/test_router_rules.py::test_match_capabilities_rejects_single_char_keyword 
[gw1] [ 29%] ERROR tests/capability/test_router_rules.py::test_tool_and_memory_intent_markers 
tests/capability/test_router_rules.py::test_match_capabilities_ignores_capability_without_provider 
[gw2] [ 29%] ERROR tests/capability/test_router_rules.py::test_match_capabilities_hits_declared_keyword 
tests/capability/test_router_rules.py::test_match_capabilities_can_hit_multiple_sorted 
[gw0] [ 30%] ERROR tests/capability/test_router_rules.py::test_match_capabilities_ignores_words_only_in_examples 
tests/capability/test_router_rules.py::test_match_capabilities_empty_message 
[gw3] [ 30%] ERROR tests/capability/test_router_rules.py::test_match_capabilities_rejects_single_char_keyword 
tests/capability/test_router_rules.py::test_keyword_hit_short_circuits_with_tool 
[gw0] [ 30%] ERROR tests/capability/test_router_rules.py::test_match_capabilities_empty_message 
tests/capability/test_router_rules.py::test_greeting_with_real_content_keeps_memory 
[gw2] [ 30%] ERROR tests/capability/test_router_rules.py::test_match_capabilities_can_hit_multiple_sorted 
[gw1] [ 30%] ERROR tests/capability/test_router_rules.py::test_match_capabilities_ignores_capability_without_provider 
tests/capability/test_router_rules.py::test_tool_marker_without_capability_defers_to_level1 
tests/capability/test_router_rules.py::test_pure_greeting_disables_memory 
[gw3] [ 30%] ERROR tests/capability/test_router_rules.py::test_keyword_hit_short_circuits_with_tool 
tests/capability/test_router_rules.py::test_greeting_with_tool_marker_is_not_greeting 
[gw1] [ 31%] ERROR tests/capability/test_router_rules.py::test_tool_marker_without_capability_defers_to_level1 
tests/capability/test_router_rules.py::test_keyword_hit_with_memory_marker_keeps_both 
[gw2] [ 31%] ERROR tests/capability/test_router_rules.py::test_pure_greeting_disables_memory 
tests/capability/test_router_rules.py::test_memory_marker_with_tool_marker_defers 
[gw0] [ 31%] ERROR tests/capability/test_router_rules.py::test_greeting_with_real_content_keeps_memory 
tests/capability/test_router_rules.py::test_memory_marker_short_circuits_without_tool 
[gw3] [ 31%] ERROR tests/capability/test_router_rules.py::test_greeting_with_tool_marker_is_not_greeting 
tests/capability/test_router_rules.py::test_plain_chat_defers_to_level1 
[gw1] [ 31%] ERROR tests/capability/test_router_rules.py::test_keyword_hit_with_memory_marker_keeps_both 
tests/capability/test_router_rules.py::test_empty_message_needs_nothing 
[gw2] [ 31%] ERROR tests/capability/test_router_rules.py::test_memory_marker_with_tool_marker_defers 
tests/capability/test_router_rules.py::test_auto_derived_capability_has_no_level0_matching 
[gw0] [ 31%] ERROR tests/capability/test_router_rules.py::test_memory_marker_short_circuits_without_tool 
tests/capability/test_router_semantic.py::test_mean_vector_averages_and_normalizes 
[gw3] [ 32%] ERROR tests/capability/test_router_rules.py::test_plain_chat_defers_to_level1 
tests/capability/test_router_semantic.py::test_mean_vector_drops_mismatched_dimensions 
[gw1] [ 32%] ERROR tests/capability/test_router_rules.py::test_empty_message_needs_nothing 
tests/capability/test_router_semantic.py::test_mean_vector_handles_empty_and_zero 
[gw0] [ 32%] ERROR tests/capability/test_router_semantic.py::test_mean_vector_averages_and_normalizes 
tests/capability/test_router_semantic.py::test_capability_with_all_encodings_failed_is_dropped 
[gw3] [ 32%] ERROR tests/capability/test_router_semantic.py::test_mean_vector_drops_mismatched_dimensions 
tests/capability/test_router_semantic.py::test_prototype_cache_reused_when_registry_unchanged 
[gw2] [ 32%] ERROR tests/capability/test_router_rules.py::test_auto_derived_capability_has_no_level0_matching 
tests/capability/test_router_semantic.py::test_prototypes_average_examples_and_description 
[gw1] [ 32%] ERROR tests/capability/test_router_semantic.py::test_mean_vector_handles_empty_and_zero 
tests/capability/test_router_semantic.py::test_prototype_cache_invalidated_on_registry_change 
[gw2] [ 33%] ERROR tests/capability/test_router_semantic.py::test_prototypes_average_examples_and_description 
tests/capability/test_router_semantic.py::test_score_returns_none_when_query_encoding_fails 
[gw0] [ 33%] ERROR tests/capability/test_router_semantic.py::test_capability_with_all_encodings_failed_is_dropped 
[gw3] [ 33%] ERROR tests/capability/test_router_semantic.py::test_prototype_cache_reused_when_registry_unchanged 
tests/capability/test_router_semantic.py::test_prototype_cache_invalidated_on_model_change 
tests/capability/test_router_semantic.py::test_score_capabilities_sorted_desc 
[gw1] [ 33%] ERROR tests/capability/test_router_semantic.py::test_prototype_cache_invalidated_on_registry_change 
tests/capability/test_router_semantic.py::test_score_returns_none_when_no_routable_capability 
[gw2] [ 33%] ERROR tests/capability/test_router_semantic.py::test_score_returns_none_when_query_encoding_fails 
tests/capability/test_router_semantic.py::test_score_returns_none_for_blank_message 
[gw0] [ 33%] ERROR tests/capability/test_router_semantic.py::test_prototype_cache_invalidated_on_model_change 
[gw3] [ 34%] ERROR tests/capability/test_router_semantic.py::test_score_capabilities_sorted_desc 
tests/capability/test_router_semantic.py::test_score_is_deterministic_on_ties 
tests/capability/test_router_semantic.py::test_route_semantic_flags_tool_above_threshold 
[gw1] [ 34%] ERROR tests/capability/test_router_semantic.py::test_score_returns_none_when_no_routable_capability 
tests/capability/test_router_semantic.py::test_route_semantic_reports_no_tool_below_threshold 
[gw0] [ 34%] ERROR tests/capability/test_router_semantic.py::test_score_is_deterministic_on_ties 
[gw3] [ 34%] ERROR tests/capability/test_router_semantic.py::test_route_semantic_flags_tool_above_threshold 
tests/capability/test_router_semantic.py::test_route_semantic_passes_memory_through 
tests/capability/test_router_semantic.py::test_route_semantic_threshold_is_configurable 
[gw2] [ 34%] ERROR tests/capability/test_router_semantic.py::test_score_returns_none_for_blank_message 
tests/capability/test_router_semantic.py::test_route_semantic_respects_max_capabilities 
[gw1] [ 34%] ERROR tests/capability/test_router_semantic.py::test_route_semantic_reports_no_tool_below_threshold 
tests/capability/test_router_semantic.py::test_route_semantic_returns_none_when_unusable 
[gw2] [ 35%] ERROR tests/capability/test_router_semantic.py::test_route_semantic_respects_max_capabilities 
tests/capability/test_router_semantic.py::test_select_hits_margin_cannot_be_replaced_by_absolute_floor 
[gw0] [ 35%] ERROR tests/capability/test_router_semantic.py::test_route_semantic_threshold_is_configurable 
tests/capability/test_router_semantic.py::test_select_hits_drops_passengers_by_margin 
[gw3] [ 35%] ERROR tests/capability/test_router_semantic.py::test_route_semantic_passes_memory_through 
tests/capability/test_router_semantic.py::test_select_hits_keeps_genuine_multi_capability_request 
[gw1] [ 35%] ERROR tests/capability/test_router_semantic.py::test_route_semantic_returns_none_when_unusable 
tests/capability/test_router_semantic.py::test_select_hits_margin_zero_disables_cut 
[gw2] [ 35%] ERROR tests/capability/test_router_semantic.py::test_select_hits_margin_cannot_be_replaced_by_absolute_floor 
tests/capability/test_router_semantic.py::test_select_hits_absolute_floor_still_applies 
[gw0] [ 35%] ERROR tests/capability/test_router_semantic.py::test_select_hits_drops_passengers_by_margin 
tests/capability/test_router_semantic.py::test_select_hits_respects_max_capabilities 
[gw3] [ 36%] ERROR tests/capability/test_router_semantic.py::test_select_hits_keeps_genuine_multi_capability_request 
tests/capability/test_router_semantic.py::test_select_hits_empty 
[gw1] [ 36%] ERROR tests/capability/test_router_semantic.py::test_select_hits_margin_zero_disables_cut 
tests/capability/test_router_semantic.py::test_route_semantic_applies_margin 
[gw2] [ 36%] ERROR tests/capability/test_router_semantic.py::test_select_hits_absolute_floor_still_applies 
tests/capability/test_router_semantic.py::test_no_tool_route_lists_hits_without_margin_cut 
[gw0] [ 36%] ERROR tests/capability/test_router_semantic.py::test_select_hits_respects_max_capabilities 
tests/capability/test_router_semantic.py::test_prototypes_written_incrementally_survive_cancellation 
[gw3] [ 36%] ERROR tests/capability/test_router_semantic.py::test_select_hits_empty 
tests/capability/test_router_semantic.py::test_failed_capability_is_retried_next_time 
[gw1] [ 36%] ERROR tests/capability/test_router_semantic.py::test_route_semantic_applies_margin 
tests/capability/test_router_semantic.py::test_warmup_fills_cache 
[gw2] [ 36%] ERROR tests/capability/test_router_semantic.py::test_no_tool_route_lists_hits_without_margin_cut 
tests/capability/test_router_semantic.py::test_warmup_never_raises_on_timeout 
[gw0] [ 37%] ERROR tests/capability/test_router_semantic.py::test_prototypes_written_incrementally_survive_cancellation 
tests/capability/test_router_semantic.py::test_warmup_never_raises_on_error 
[gw3] [ 37%] ERROR tests/capability/test_router_semantic.py::test_failed_capability_is_retried_next_time 
tests/capability/test_tasks.py::test_task_id_is_monotonic 
[gw1] [ 37%] ERROR tests/capability/test_router_semantic.py::test_warmup_fills_cache 
tests/capability/test_tasks.py::test_task_type_is_str_enum 
[gw2] [ 37%] ERROR tests/capability/test_router_semantic.py::test_warmup_never_raises_on_timeout 
tests/capability/test_tasks.py::test_task_defaults_are_independent 
[gw0] [ 37%] ERROR tests/capability/test_router_semantic.py::test_warmup_never_raises_on_error 
tests/capability/test_tasks.py::test_result_ok_covers_success_and_partial 
[gw3] [ 37%] ERROR tests/capability/test_tasks.py::test_task_id_is_monotonic 
tests/capability/test_tasks.py::test_failed_and_cancelled_are_distinct 
[gw1] [ 38%] ERROR tests/capability/test_tasks.py::test_task_type_is_str_enum 
tests/capability/test_tasks.py::test_result_repr_does_not_dump_full_data 
[gw2] [ 38%] ERROR tests/capability/test_tasks.py::test_task_defaults_are_independent 
tests/capability/test_tasks.py::test_add_rejects_duplicate_id 
[gw0] [ 38%] ERROR tests/capability/test_tasks.py::test_result_ok_covers_success_and_partial 
tests/capability/test_tasks.py::test_validate_rejects_dangling_dependency 
[gw3] [ 38%] ERROR tests/capability/test_tasks.py::test_failed_and_cancelled_are_distinct 
tests/capability/test_tasks.py::test_ready_returns_only_unblocked_tasks 
[gw1] [ 38%] ERROR tests/capability/test_tasks.py::test_result_repr_does_not_dump_full_data 
tests/capability/test_tasks.py::test_topological_order_groups_parallel_tasks 
[gw2] [ 38%] ERROR tests/capability/test_tasks.py::test_add_rejects_duplicate_id 
tests/capability/test_tasks.py::test_topological_order_detects_cycle 
[gw0] [ 39%] ERROR tests/capability/test_tasks.py::test_validate_rejects_dangling_dependency 
tests/capability/test_tasks.py::test_topological_order_is_deterministic 
[gw3] [ 39%] ERROR tests/capability/test_tasks.py::test_ready_returns_only_unblocked_tasks 
tests/capability/test_tasks.py::test_empty_graph_is_falsy_and_orders_to_nothing 
[gw1] [ 39%] ERROR tests/capability/test_tasks.py::test_topological_order_groups_parallel_tasks 
tests/test_benchmark.py::test_benchmark_loads_cases 
[gw2] [ 39%] ERROR tests/capability/test_tasks.py::test_topological_order_detects_cycle 
tests/test_benchmark.py::test_benchmark_run_metrics_within_targets 
[gw0] [ 39%] ERROR tests/capability/test_tasks.py::test_topological_order_is_deterministic 
tests/test_benchmark.py::test_benchmark_results_expose_ranked_all_and_separation 
[gw3] [ 39%] ERROR tests/capability/test_tasks.py::test_empty_graph_is_falsy_and_orders_to_nothing 
tests/test_benchmark.py::test_benchmark_ok_flag_reflects_expected 
[gw1] [ 40%] ERROR tests/test_benchmark.py::test_benchmark_loads_cases 
tests/test_benchmark.py::test_benchmark_rank_recommend_001_is_ok 
[gw2] [ 40%] ERROR tests/test_benchmark.py::test_benchmark_run_metrics_within_targets 
tests/test_benchmark.py::test_benchmark_verbose_scores_present 
[gw0] [ 40%] ERROR tests/test_benchmark.py::test_benchmark_results_expose_ranked_all_and_separation 
tests/test_benchmark.py::test_benchmark_embedding_fixture_path 
[gw3] [ 40%] ERROR tests/test_benchmark.py::test_benchmark_ok_flag_reflects_expected 
tests/test_consolidation_prompt.py::test_no_fabrication_clauses_present 
[gw1] [ 40%] ERROR tests/test_benchmark.py::test_benchmark_rank_recommend_001_is_ok 
tests/test_consolidation_prompt.py::test_attribution_clause_present 
[gw0] [ 40%] ERROR tests/test_benchmark.py::test_benchmark_embedding_fixture_path 
[gw2] [ 40%] ERROR tests/test_benchmark.py::test_benchmark_verbose_scores_present 
tests/test_consolidation_prompt.py::test_empty_array_permission_present 
tests/test_consolidation_prompt.py::test_bot_self_clause_present 
[gw3] [ 41%] ERROR tests/test_consolidation_prompt.py::test_no_fabrication_clauses_present 
tests/test_consolidation_prompt.py::test_describes_whom_criterion_present 
[gw1] [ 41%] ERROR tests/test_consolidation_prompt.py::test_attribution_clause_present 
tests/test_consolidation_prompt.py::test_no_hard_confidence_floor 
[gw2] [ 41%] ERROR tests/test_consolidation_prompt.py::test_bot_self_clause_present 
tests/test_consolidation_prompt.py::test_format_fills_placeholders 
[gw0] [ 41%] ERROR tests/test_consolidation_prompt.py::test_empty_array_permission_present 
tests/test_consolidation_prompt.py::test_no_negative_example_blocks 
[gw3] [ 41%] ERROR tests/test_consolidation_prompt.py::test_describes_whom_criterion_present 
tests/test_deploy_checks.py::test_healthy_snapshot_is_all_ok 
[gw1] [ 41%] ERROR tests/test_consolidation_prompt.py::test_no_hard_confidence_floor 
tests/test_deploy_checks.py::test_total_checks_positive_and_consistent 
[gw2] [ 42%] ERROR tests/test_consolidation_prompt.py::test_format_fills_placeholders 
tests/test_deploy_checks.py::test_report_summary_derives_ok_from_total 
[gw0] [ 42%] ERROR tests/test_consolidation_prompt.py::test_no_negative_example_blocks 
tests/test_deploy_checks.py::test_to_json_gui_contract 
[gw3] [ 42%] ERROR tests/test_deploy_checks.py::test_healthy_snapshot_is_all_ok 
tests/test_deploy_checks.py::test_to_json_llm_section_shows_effective_routing 
[gw1] [ 42%] ERROR tests/test_deploy_checks.py::test_total_checks_positive_and_consistent 
tests/test_deploy_checks.py::test_to_json_llm_section_never_carries_api_key_values 
[gw2] [ 42%] ERROR tests/test_deploy_checks.py::test_report_summary_derives_ok_from_total 
tests/test_deploy_checks.py::test_to_terminal_prints_role_to_endpoint_table 
[gw0] [ 42%] ERROR tests/test_deploy_checks.py::test_to_json_gui_contract 
tests/test_deploy_checks.py::test_to_terminal_without_snapshot_is_unchanged 
[gw3] [ 43%] ERROR tests/test_deploy_checks.py::test_to_json_llm_section_shows_effective_routing 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides0] 
[gw1] [ 43%] ERROR tests/test_deploy_checks.py::test_to_json_llm_section_never_carries_api_key_values 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides1] 
[gw2] [ 43%] ERROR tests/test_deploy_checks.py::test_to_terminal_prints_role_to_endpoint_table 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides2] 
[gw0] [ 43%] ERROR tests/test_deploy_checks.py::test_to_terminal_without_snapshot_is_unchanged 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides3] 
[gw3] [ 43%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides0] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides4] 
[gw1] [ 43%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides1] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides5] 
[gw2] [ 44%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides2] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides6] 
[gw0] [ 44%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides3] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides7] 
[gw3] [ 44%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides4] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides8] 
[gw1] [ 44%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides5] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides9] 
[gw2] [ 44%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides6] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides10] 
[gw0] [ 44%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides7] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides11] 
[gw3] [ 45%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides8] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides12] 
[gw1] [ 45%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides9] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides13] 
[gw0] [ 45%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides11] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides15] 
[gw2] [ 45%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides10] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides14] 
[gw3] [ 45%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides12] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides16] 
[gw1] [ 45%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides13] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides17] 
[gw2] [ 45%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides14] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides19] 
[gw0] [ 46%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides15] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides18] 
[gw3] [ 46%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides16] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides20] 
[gw1] [ 46%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides17] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides21] 
[gw2] [ 46%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides19] 
tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides22] 
[gw0] [ 46%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides18] 
tests/test_deploy_checks.py::test_run_all_sorts_error_warn_ok 
[gw3] [ 46%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides20] 
tests/test_deploy_checks.py::test_run_all_flattens_multi_result_check 
[gw1] [ 47%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides21] 
tests/test_deploy_checks.py::test_python_version_too_old 
[gw0] [ 47%] ERROR tests/test_deploy_checks.py::test_run_all_sorts_error_warn_ok 
[gw2] [ 47%] ERROR tests/test_deploy_checks.py::test_all_non_ok_results_have_fix_hint[overrides22] 
tests/test_deploy_checks.py::test_python_version_ok 
tests/test_deploy_checks.py::test_python_310_missing_tomli 
[gw3] [ 47%] ERROR tests/test_deploy_checks.py::test_run_all_flattens_multi_result_check 
tests/test_deploy_checks.py::test_dependencies_missing 
[gw1] [ 47%] ERROR tests/test_deploy_checks.py::test_python_version_too_old 
tests/test_deploy_checks.py::test_env_file_missing 
[gw2] [ 47%] ERROR tests/test_deploy_checks.py::test_python_310_missing_tomli 
tests/test_deploy_checks.py::test_onebot_mode_unknown 
[gw0] [ 48%] ERROR tests/test_deploy_checks.py::test_python_version_ok 
tests/test_deploy_checks.py::test_allowed_groups_empty 
[gw3] [ 48%] ERROR tests/test_deploy_checks.py::test_dependencies_missing 
tests/test_deploy_checks.py::test_onebot_reverse_port_busy_is_warn 
[gw1] [ 48%] ERROR tests/test_deploy_checks.py::test_env_file_missing 
tests/test_deploy_checks.py::test_onebot_reverse_port_busy_but_self_is_ok 
[gw2] [ 48%] ERROR tests/test_deploy_checks.py::test_onebot_mode_unknown 
tests/test_deploy_checks.py::test_onebot_reverse_port_free_ok 
[gw0] [ 48%] ERROR tests/test_deploy_checks.py::test_allowed_groups_empty 
tests/test_deploy_checks.py::test_onebot_reverse_port_probe_failed_is_warn 
[gw3] [ 48%] ERROR tests/test_deploy_checks.py::test_onebot_reverse_port_busy_is_warn 
tests/test_deploy_checks.py::test_onebot_forward_unreachable_is_error 
[gw1] [ 49%] ERROR tests/test_deploy_checks.py::test_onebot_reverse_port_busy_but_self_is_ok 
tests/test_deploy_checks.py::test_onebot_forward_ok 
[gw2] [ 49%] ERROR tests/test_deploy_checks.py::test_onebot_reverse_port_free_ok 
tests/test_deploy_checks.py::test_lm_studio_unreachable_is_error 
[gw0] [ 49%] ERROR tests/test_deploy_checks.py::test_onebot_reverse_port_probe_failed_is_warn 
tests/test_deploy_checks.py::test_lm_studio_probe_failed_is_warn 
[gw3] [ 49%] ERROR tests/test_deploy_checks.py::test_onebot_forward_unreachable_is_error 
tests/test_deploy_checks.py::test_lm_model_chat_not_loaded_suggests 
[gw1] [ 49%] ERROR tests/test_deploy_checks.py::test_onebot_forward_ok 
tests/test_deploy_checks.py::test_lm_model_chat_empty_is_warn 
[gw2] [ 49%] ERROR tests/test_deploy_checks.py::test_lm_studio_unreachable_is_error 
tests/test_deploy_checks.py::test_lm_model_consolidation_not_loaded_is_error 
[gw0] [ 50%] ERROR tests/test_deploy_checks.py::test_lm_studio_probe_failed_is_warn 
tests/test_deploy_checks.py::test_lm_model_extract_not_loaded_is_warn 
[gw3] [ 50%] ERROR tests/test_deploy_checks.py::test_lm_model_chat_not_loaded_suggests 
tests/test_deploy_checks.py::test_lm_model_extract_empty_skipped 
[gw1] [ 50%] ERROR tests/test_deploy_checks.py::test_lm_model_chat_empty_is_warn 
tests/test_deploy_checks.py::test_lm_model_embedding_disabled_skipped 
[gw2] [ 50%] ERROR tests/test_deploy_checks.py::test_lm_model_consolidation_not_loaded_is_error 
tests/test_deploy_checks.py::test_lm_model_embedding_not_loaded_is_error 
[gw0] [ 50%] ERROR tests/test_deploy_checks.py::test_lm_model_extract_not_loaded_is_warn 
tests/test_deploy_checks.py::test_suggest_model_close_match 
[gw3] [ 50%] ERROR tests/test_deploy_checks.py::test_lm_model_extract_empty_skipped 
tests/test_deploy_checks.py::test_db_missing_returns_none 
[gw2] [ 50%] ERROR tests/test_deploy_checks.py::test_lm_model_embedding_not_loaded_is_error 
tests/test_deploy_checks.py::test_db_writable_unknown_is_warn 
[gw1] [ 51%] ERROR tests/test_deploy_checks.py::test_lm_model_embedding_disabled_skipped 
tests/test_deploy_checks.py::test_db_not_writable_is_error 
[gw0] [ 51%] ERROR tests/test_deploy_checks.py::test_suggest_model_close_match 
tests/test_deploy_checks.py::test_schema_lower_is_warn 
[gw3] [ 51%] ERROR tests/test_deploy_checks.py::test_db_missing_returns_none 
tests/test_deploy_checks.py::test_schema_higher_is_error 
[gw2] [ 51%] ERROR tests/test_deploy_checks.py::test_db_writable_unknown_is_warn 
tests/test_deploy_checks.py::test_schema_matching_is_ok 
[gw1] [ 51%] ERROR tests/test_deploy_checks.py::test_db_not_writable_is_error 
tests/test_deploy_checks.py::test_schema_unknown_is_warn 
[gw0] [ 51%] ERROR tests/test_deploy_checks.py::test_schema_lower_is_warn 
tests/test_deploy_checks.py::test_schema_version_skipped_when_db_missing 
[gw3] [ 52%] ERROR tests/test_deploy_checks.py::test_schema_higher_is_error 
tests/test_deploy_checks.py::test_all_empty_config_has_no_noise_ids 
[gw2] [ 52%] ERROR tests/test_deploy_checks.py::test_schema_matching_is_ok 
tests/test_deploy_checks.py::test_stella_home_reports_split_layout 
[gw1] [ 52%] ERROR tests/test_deploy_checks.py::test_schema_unknown_is_warn 
tests/test_deploy_checks.py::test_stella_home_without_pointer_is_warn 
[gw0] [ 52%] ERROR tests/test_deploy_checks.py::test_schema_version_skipped_when_db_missing 
tests/test_deploy_checks.py::test_stella_home_legacy_layout_is_ok 
[gw3] [ 52%] ERROR tests/test_deploy_checks.py::test_all_empty_config_has_no_noise_ids 
tests/test_deploy_checks.py::test_stella_home_portable_mode_is_ok_but_warns_about_the_cost 
[gw2] [ 52%] ERROR tests/test_deploy_checks.py::test_stella_home_reports_split_layout 
tests/test_deploy_checks.py::test_version_marks_downgrade_is_warn 
[gw1] [ 53%] ERROR tests/test_deploy_checks.py::test_stella_home_without_pointer_is_warn 
tests/test_deploy_checks.py::test_version_marks_first_run_points_to_migrate 
[gw0] [ 53%] ERROR tests/test_deploy_checks.py::test_stella_home_legacy_layout_is_ok 
tests/test_deploy_checks.py::test_version_marks_upgrade_is_reported 
[gw3] [ 53%] ERROR tests/test_deploy_checks.py::test_stella_home_portable_mode_is_ok_but_warns_about_the_cost 
tests/test_deploy_checks.py::test_version_marks_read_error_is_warn 
[gw2] [ 53%] ERROR tests/test_deploy_checks.py::test_version_marks_downgrade_is_warn 
tests/test_deploy_checks.py::test_version_marks_absent_when_version_unknown 
[gw1] [ 53%] ERROR tests/test_deploy_checks.py::test_version_marks_first_run_points_to_migrate 
tests/test_deploy_checks.py::test_legacy_group_id_tables_is_warn_and_points_to_migrate 
[gw0] [ 53%] ERROR tests/test_deploy_checks.py::test_version_marks_upgrade_is_reported 
tests/test_deploy_checks.py::test_source_kind_all_empty_is_error 
[gw3] [ 54%] ERROR tests/test_deploy_checks.py::test_version_marks_read_error_is_warn 
tests/test_deploy_checks.py::test_source_kind_normal_ok 
[gw2] [ 54%] ERROR tests/test_deploy_checks.py::test_version_marks_absent_when_version_unknown 
tests/test_deploy_checks.py::test_at_mention_health_flagged 
[gw1] [ 54%] ERROR tests/test_deploy_checks.py::test_legacy_group_id_tables_is_warn_and_points_to_migrate 
tests/test_deploy_checks.py::test_at_mention_health_ok 
[gw0] [ 54%] ERROR tests/test_deploy_checks.py::test_source_kind_all_empty_is_error 
tests/test_deploy_checks.py::test_at_mention_health_no_data 
[gw3] [ 54%] ERROR tests/test_deploy_checks.py::test_source_kind_normal_ok 
tests/test_deploy_checks.py::test_space_conflicts_is_error 
[gw2] [ 54%] ERROR tests/test_deploy_checks.py::test_at_mention_health_flagged 
tests/test_deploy_checks.py::test_space_assignment_mismatch_is_warn 
[gw1] [ 54%] ERROR tests/test_deploy_checks.py::test_at_mention_health_ok 
tests/test_deploy_checks.py::test_persona_missing_is_warn 
[gw0] [ 55%] ERROR tests/test_deploy_checks.py::test_at_mention_health_no_data 
tests/test_deploy_checks.py::test_persona_empty_is_warn 
[gw3] [ 55%] ERROR tests/test_deploy_checks.py::test_space_conflicts_is_error 
tests/test_deploy_checks.py::test_disk_low_is_error 
[gw2] [ 55%] ERROR tests/test_deploy_checks.py::test_space_assignment_mismatch_is_warn 
tests/test_deploy_checks.py::test_disk_medium_is_warn 
[gw1] [ 55%] ERROR tests/test_deploy_checks.py::test_persona_missing_is_warn 
tests/test_deploy_checks.py::test_disk_unknown_is_warn 
[gw0] [ 55%] ERROR tests/test_deploy_checks.py::test_persona_empty_is_warn 
tests/test_deploy_checks.py::test_db_cleanup_on_start_warn 
[gw3] [ 55%] ERROR tests/test_deploy_checks.py::test_disk_low_is_error 
tests/test_deploy_checks.py::test_deprecated_env_single_secret_returns_both 
[gw2] [ 56%] ERROR tests/test_deploy_checks.py::test_disk_medium_is_warn 
tests/test_deploy_checks.py::test_deprecated_env_with_secret_returns_two 
[gw1] [ 56%] ERROR tests/test_deploy_checks.py::test_disk_unknown_is_warn 
tests/test_deploy_checks.py::test_deprecated_env_plain_returns_one 
[gw0] [ 56%] ERROR tests/test_deploy_checks.py::test_db_cleanup_on_start_warn 
tests/test_deploy_checks.py::test_deprecated_env_none 
[gw3] [ 56%] ERROR tests/test_deploy_checks.py::test_deprecated_env_single_secret_returns_both 
tests/test_deploy_checks.py::test_superseded_env_keys_names_the_replacement 
[gw2] [ 56%] ERROR tests/test_deploy_checks.py::test_deprecated_env_with_secret_returns_two 
tests/test_deploy_checks.py::test_superseded_env_keys_none_when_clean 
[gw1] [ 56%] ERROR tests/test_deploy_checks.py::test_deprecated_env_plain_returns_one 
tests/test_deploy_checks.py::test_llm_config_issues_are_grouped_by_level 
[gw0] [ 57%] ERROR tests/test_deploy_checks.py::test_deprecated_env_none 
tests/test_deploy_checks.py::test_llm_config_issues_none_when_clean 
[gw3] [ 57%] ERROR tests/test_deploy_checks.py::test_superseded_env_keys_names_the_replacement 
tests/test_deploy_checks.py::test_llm_endpoint_online_unreachable_is_only_warn 
[gw2] [ 57%] ERROR tests/test_deploy_checks.py::test_superseded_env_keys_none_when_clean 
tests/test_deploy_checks.py::test_llm_endpoint_local_unreachable_is_error 
[gw1] [ 57%] ERROR tests/test_deploy_checks.py::test_llm_config_issues_are_grouped_by_level 
tests/test_deploy_checks.py::test_llm_endpoint_unprobed_is_not_reported 
[gw0] [ 57%] ERROR tests/test_deploy_checks.py::test_llm_config_issues_none_when_clean 
tests/test_deploy_checks.py::test_llm_endpoint_sharing_lm_studio_address_is_not_reported_twice 
[gw3] [ 57%] ERROR tests/test_deploy_checks.py::test_llm_endpoint_online_unreachable_is_only_warn 
tests/test_deploy_checks.py::test_llm_role_model_not_listed_is_warn_with_suggestion 
[gw2] [ 58%] ERROR tests/test_deploy_checks.py::test_llm_endpoint_local_unreachable_is_error 
tests/test_deploy_checks.py::test_llm_role_model_ok_when_listed 
[gw1] [ 58%] ERROR tests/test_deploy_checks.py::test_llm_endpoint_unprobed_is_not_reported 
[gw0] [ 58%] ERROR tests/test_deploy_checks.py::test_llm_endpoint_sharing_lm_studio_address_is_not_reported_twice 
tests/test_deploy_checks.py::test_llm_role_model_skipped_when_endpoint_lists_nothing 
tests/test_deploy_checks.py::test_llm_role_model_empty_is_left_to_registry 
[gw3] [ 58%] ERROR tests/test_deploy_checks.py::test_llm_role_model_not_listed_is_warn_with_suggestion 
tests/test_deploy_checks.py::test_llm_role_model_ignores_local_roles 
[gw2] [ 58%] ERROR tests/test_deploy_checks.py::test_llm_role_model_ok_when_listed 
tests/test_deploy_checks.py::test_legacy_lm_model_check_skipped_when_role_moved_online[chat-check_lm_model_chat-overrides0] 
[gw1] [ 58%] ERROR tests/test_deploy_checks.py::test_llm_role_model_skipped_when_endpoint_lists_nothing 
tests/test_deploy_checks.py::test_legacy_lm_model_check_skipped_when_role_moved_online[consolidation-check_lm_model_consolidation-overrides1] 
[gw0] [ 59%] ERROR tests/test_deploy_checks.py::test_llm_role_model_empty_is_left_to_registry 
tests/test_deploy_checks.py::test_legacy_lm_model_check_skipped_when_role_moved_online[extract-check_lm_model_extract-overrides2] 
[gw3] [ 59%] ERROR tests/test_deploy_checks.py::test_llm_role_model_ignores_local_roles 
tests/test_deploy_checks.py::test_embedding_locality_online_endpoint_is_warn 
[gw2] [ 59%] ERROR tests/test_deploy_checks.py::test_legacy_lm_model_check_skipped_when_role_moved_online[chat-check_lm_model_chat-overrides0] 
tests/test_deploy_checks.py::test_embedding_locality_local_address_is_ok 
[gw1] [ 59%] ERROR tests/test_deploy_checks.py::test_legacy_lm_model_check_skipped_when_role_moved_online[consolidation-check_lm_model_consolidation-overrides1] 
tests/test_deploy_checks.py::test_embedding_locality_skipped_when_disabled 
[gw0] [ 59%] ERROR tests/test_deploy_checks.py::test_legacy_lm_model_check_skipped_when_role_moved_online[extract-check_lm_model_extract-overrides2] 
tests/test_deploy_checks.py::test_embedding_model_check_skipped_when_pointing_elsewhere 
[gw3] [ 59%] ERROR tests/test_deploy_checks.py::test_embedding_locality_online_endpoint_is_warn 
tests/test_deploy_checks.py::test_usage_accounting_unwritable_table_is_warn 
[gw2] [ 59%] ERROR tests/test_deploy_checks.py::test_embedding_locality_local_address_is_ok 
tests/test_deploy_checks.py::test_usage_accounting_ok_when_table_writable 
[gw0] [ 60%] ERROR tests/test_deploy_checks.py::test_embedding_model_check_skipped_when_pointing_elsewhere 
[gw1] [ 60%] ERROR tests/test_deploy_checks.py::test_embedding_locality_skipped_when_disabled 
tests/test_deploy_checks.py::test_usage_accounting_skipped_when_turned_off 
tests/test_deploy_checks.py::test_usage_accounting_skipped_when_probe_failed 
[gw3] [ 60%] ERROR tests/test_deploy_checks.py::test_usage_accounting_unwritable_table_is_warn 
tests/test_deploy_checks.py::test_budget_unlimited_is_never_reported 
[gw2] [ 60%] ERROR tests/test_deploy_checks.py::test_usage_accounting_ok_when_table_writable 
tests/test_deploy_checks.py::test_budget_below_eighty_percent_is_quiet 
[gw1] [ 60%] ERROR tests/test_deploy_checks.py::test_usage_accounting_skipped_when_probe_failed 
tests/test_deploy_checks.py::test_budget_over_is_warn_not_error 
[gw0] [ 60%] ERROR tests/test_deploy_checks.py::test_usage_accounting_skipped_when_turned_off 
tests/test_deploy_checks.py::test_budget_at_eighty_percent_warns_early 
[gw3] [ 61%] ERROR tests/test_deploy_checks.py::test_budget_unlimited_is_never_reported 
tests/test_deploy_checks.py::test_budget_survives_garbage_values 
[gw2] [ 61%] ERROR tests/test_deploy_checks.py::test_budget_below_eighty_percent_is_quiet 
tests/test_deploy_checks.py::test_fallback_state_reports_only_active_degradation 
[gw1] [ 61%] ERROR tests/test_deploy_checks.py::test_budget_over_is_warn_not_error 
tests/test_deploy_checks.py::test_fallback_state_quiet_when_nothing_is_degraded 
[gw0] [ 61%] ERROR tests/test_deploy_checks.py::test_budget_at_eighty_percent_warns_early 
tests/test_deploy_checks.py::test_usage_checks_carry_no_credentials 
[gw3] [ 61%] ERROR tests/test_deploy_checks.py::test_budget_survives_garbage_values 
tests/test_deploy_process.py::test_pid_roundtrip 
[gw2] [ 61%] ERROR tests/test_deploy_checks.py::test_fallback_state_reports_only_active_degradation 
tests/test_deploy_process.py::test_read_pid_invalid_content 
[gw1] [ 62%] ERROR tests/test_deploy_checks.py::test_fallback_state_quiet_when_nothing_is_degraded 
tests/test_deploy_process.py::test_is_alive_true_for_running 
[gw0] [ 62%] ERROR tests/test_deploy_checks.py::test_usage_checks_carry_no_credentials 
tests/test_deploy_process.py::test_is_alive_false_for_dead 
[gw3] [ 62%] ERROR tests/test_deploy_process.py::test_pid_roundtrip 
tests/test_deploy_process.py::test_is_alive_bogus_pid 
[gw2] [ 62%] ERROR tests/test_deploy_process.py::test_read_pid_invalid_content 
tests/test_deploy_process.py::test_is_alive_false_for_unreaped_child 
[gw1] [ 62%] ERROR tests/test_deploy_process.py::test_is_alive_true_for_running 
tests/test_deploy_process.py::test_stat_is_zombie_true 
[gw0] [ 62%] ERROR tests/test_deploy_process.py::test_is_alive_false_for_dead 
tests/test_deploy_process.py::test_stat_is_zombie_false_running 
[gw3] [ 63%] ERROR tests/test_deploy_process.py::test_is_alive_bogus_pid 
tests/test_deploy_process.py::test_stat_is_zombie_comm_with_parens 
[gw2] [ 63%] ERROR tests/test_deploy_process.py::test_is_alive_false_for_unreaped_child 
tests/test_deploy_process.py::test_is_zombie_nonexistent_pid 
[gw1] [ 63%] ERROR tests/test_deploy_process.py::test_stat_is_zombie_true 
tests/test_deploy_process.py::test_stop_no_running_process 
[gw0] [ 63%] ERROR tests/test_deploy_process.py::test_stat_is_zombie_false_running 
tests/test_deploy_process.py::test_stop_without_pid_but_api_reachable 
[gw3] [ 63%] ERROR tests/test_deploy_process.py::test_stat_is_zombie_comm_with_parens 
tests/test_deploy_process.py::test_stop_without_pid_and_api_unreachable 
[gw2] [ 63%] ERROR tests/test_deploy_process.py::test_is_zombie_nonexistent_pid 
tests/test_deploy_process.py::test_stop_writes_sentinel_before_hard_kill 
[gw1] [ 63%] ERROR tests/test_deploy_process.py::test_stop_no_running_process 
tests/test_deploy_process.py::test_stop_clears_sentinel_on_exit 
[gw0] [ 64%] ERROR tests/test_deploy_process.py::test_stop_without_pid_but_api_reachable 
tests/test_deploy_process.py::test_stop_kills_live_process 
[gw3] [ 64%] ERROR tests/test_deploy_process.py::test_stop_without_pid_and_api_unreachable 
tests/test_deploy_process.py::test_status_dict_shape 
[gw2] [ 64%] ERROR tests/test_deploy_process.py::test_stop_writes_sentinel_before_hard_kill 
tests/test_deploy_process.py::test_status_api_unreachable 
[gw1] [ 64%] ERROR tests/test_deploy_process.py::test_stop_clears_sentinel_on_exit 
[gw0] [ 64%] ERROR tests/test_deploy_process.py::test_stop_kills_live_process 
tests/test_deploy_process.py::test_status_api_reachable_without_pid_file 
tests/test_deploy_process.py::test_status_pid_file_fallback_when_api_unreachable 
[gw3] [ 64%] ERROR tests/test_deploy_process.py::test_status_dict_shape 
tests/test_deploy_process.py::test_fetch_live_status_maps_wildcard_host 
[gw2] [ 65%] ERROR tests/test_deploy_process.py::test_status_api_unreachable 
tests/test_deploy_process.py::test_fetch_live_status_unreachable_returns_none 
[gw1] [ 65%] ERROR tests/test_deploy_process.py::test_status_api_reachable_without_pid_file 
tests/test_deploy_process.py::test_fetch_live_status_non_200_returns_none 
[gw0] [ 65%] ERROR tests/test_deploy_process.py::test_status_pid_file_fallback_when_api_unreachable 
tests/test_env_inherit.py::test_unset_falls_back_to_parent 
[gw3] [ 65%] ERROR tests/test_deploy_process.py::test_fetch_live_status_maps_wildcard_host 
tests/test_env_inherit.py::test_empty_value_falls_back_to_parent 
[gw2] [ 65%] ERROR tests/test_deploy_process.py::test_fetch_live_status_unreachable_returns_none 
tests/test_env_inherit.py::test_whitespace_only_falls_back_to_parent 
[gw1] [ 65%] ERROR tests/test_deploy_process.py::test_fetch_live_status_non_200_returns_none 
tests/test_env_inherit.py::test_explicit_value_wins_and_is_stripped 
[gw0] [ 66%] ERROR tests/test_env_inherit.py::test_unset_falls_back_to_parent 
tests/test_env_inherit.py::test_env_still_distinguishes_unset_from_empty 
[gw3] [ 66%] ERROR tests/test_env_inherit.py::test_empty_value_falls_back_to_parent 
tests/test_env_inherit.py::test_inherit_pairs_were_actually_discovered 
[gw2] [ 66%] ERROR tests/test_env_inherit.py::test_whitespace_only_falls_back_to_parent 
[gw0] [ 66%] ERROR tests/test_env_inherit.py::test_env_still_distinguishes_unset_from_empty 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[ASTRBOT_LLM_MODEL-LM_STUDIO_MODEL] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[ASTRBOT_LLM_API_KEY-LM_STUDIO_API_KEY] 
[gw1] [ 66%] ERROR tests/test_env_inherit.py::test_explicit_value_wins_and_is_stripped 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[ASTRBOT_LLM_BASE_URL-LM_STUDIO_BASE_URL] 
[gw3] [ 66%] ERROR tests/test_env_inherit.py::test_inherit_pairs_were_actually_discovered 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[CONSOLIDATION_LM_STUDIO_API_KEY-LM_STUDIO_API_KEY] 
[gw2] [ 67%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[ASTRBOT_LLM_API_KEY-LM_STUDIO_API_KEY] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ENDPOINT_EXTRA_API_KEY-CONSOLIDATION_LM_STUDIO_API_KEY] 
[gw1] [ 67%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[ASTRBOT_LLM_BASE_URL-LM_STUDIO_BASE_URL] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ENDPOINT_EXTRA_BASE_URL-CONSOLIDATION_LM_STUDIO_BASE_URL] 
[gw0] [ 67%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[ASTRBOT_LLM_MODEL-LM_STUDIO_MODEL] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[CONSOLIDATION_LM_STUDIO_BASE_URL-LM_STUDIO_BASE_URL] 
[gw3] [ 67%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[CONSOLIDATION_LM_STUDIO_API_KEY-LM_STUDIO_API_KEY] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ENDPOINT_LOCAL_API_KEY-LM_STUDIO_API_KEY] 
[gw2] [ 67%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ENDPOINT_EXTRA_API_KEY-CONSOLIDATION_LM_STUDIO_API_KEY] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ENDPOINT_LOCAL_BASE_URL-LM_STUDIO_BASE_URL] 
[gw1] [ 67%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ENDPOINT_EXTRA_BASE_URL-CONSOLIDATION_LM_STUDIO_BASE_URL] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_CHAT_MODEL-LM_STUDIO_MODEL] 
[gw0] [ 68%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[CONSOLIDATION_LM_STUDIO_BASE_URL-LM_STUDIO_BASE_URL] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_COMPACT_MODEL-LM_STUDIO_MODEL] 
[gw3] [ 68%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ENDPOINT_LOCAL_API_KEY-LM_STUDIO_API_KEY] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_CONSOLIDATION_MAX_TOKENS-CONSOLIDATION_LOCAL_MAX_TOKENS] 
[gw2] [ 68%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ENDPOINT_LOCAL_BASE_URL-LM_STUDIO_BASE_URL] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_CONSOLIDATION_MODEL-CONSOLIDATION_LM_STUDIO_MODEL] 
[gw1] [ 68%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_CHAT_MODEL-LM_STUDIO_MODEL] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_CONSOLIDATION_TEMPERATURE-CONSOLIDATION_LM_STUDIO_TEMPERATURE] 
[gw0] [ 68%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_COMPACT_MODEL-LM_STUDIO_MODEL] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_EXTRACT_MAX_TOKENS-MEMORY_EXTRACT_MAX_TOKENS] 
[gw3] [ 68%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_CONSOLIDATION_MAX_TOKENS-CONSOLIDATION_LOCAL_MAX_TOKENS] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_EXTRACT_MODEL-MEMORY_EXTRACT_LM_STUDIO_MODEL] 
[gw2] [ 68%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_CONSOLIDATION_MODEL-CONSOLIDATION_LM_STUDIO_MODEL] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_EXTRACT_TEMPERATURE-MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE] 
[gw1] [ 69%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_CONSOLIDATION_TEMPERATURE-CONSOLIDATION_LM_STUDIO_TEMPERATURE] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_PLUGIN_MAX_TOKENS-ASTRBOT_LLM_MAX_TOKENS] 
[gw0] [ 69%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_EXTRACT_MAX_TOKENS-MEMORY_EXTRACT_MAX_TOKENS] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_PLUGIN_MODEL-ASTRBOT_LLM_MODEL] 
[gw3] [ 69%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_EXTRACT_MODEL-MEMORY_EXTRACT_LM_STUDIO_MODEL] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_PLUGIN_TEMPERATURE-ASTRBOT_LLM_TEMPERATURE] 
[gw2] [ 69%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_EXTRACT_TEMPERATURE-MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_ROUTER_MODEL-LM_STUDIO_MODEL] 
[gw1] [ 69%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_PLUGIN_MAX_TOKENS-ASTRBOT_LLM_MAX_TOKENS] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[MEMORY_EXTRACT_LM_STUDIO_API_KEY-LM_STUDIO_API_KEY] 
[gw0] [ 69%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_PLUGIN_MODEL-ASTRBOT_LLM_MODEL] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[MEMORY_EXTRACT_LM_STUDIO_BASE_URL-LM_STUDIO_BASE_URL] 
[gw3] [ 70%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_PLUGIN_TEMPERATURE-ASTRBOT_LLM_TEMPERATURE] 
tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[MEMORY_EXTRACT_LM_STUDIO_MODEL-LM_STUDIO_MODEL] 
[gw2] [ 70%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[LLM_ROLE_ROUTER_MODEL-LM_STUDIO_MODEL] 
tests/test_env_merge.py::test_user_values_are_carried_over 
[gw1] [ 70%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[MEMORY_EXTRACT_LM_STUDIO_API_KEY-LM_STUDIO_API_KEY] 
tests/test_env_merge.py::test_template_comments_survive 
[gw0] [ 70%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[MEMORY_EXTRACT_LM_STUDIO_BASE_URL-LM_STUDIO_BASE_URL] 
tests/test_env_merge.py::test_new_keys_stay_at_template_default 
[gw3] [ 70%] ERROR tests/test_env_inherit.py::test_resolved_settings_never_empty_when_parent_is_set[MEMORY_EXTRACT_LM_STUDIO_MODEL-LM_STUDIO_MODEL] 
tests/test_env_merge.py::test_deprecated_keys_removed_with_reason 
[gw0] [ 70%] ERROR tests/test_env_merge.py::test_new_keys_stay_at_template_default 
tests/test_env_merge.py::test_report_never_prints_secret_values 
[gw2] [ 71%] ERROR tests/test_env_merge.py::test_user_values_are_carried_over 
tests/test_env_merge.py::test_unknown_keys_kept_at_end 
[gw1] [ 71%] ERROR tests/test_env_merge.py::test_template_comments_survive 
tests/test_env_merge.py::test_key_known_to_code_but_missing_from_template_is_appended 
[gw3] [ 71%] ERROR tests/test_env_merge.py::test_deprecated_keys_removed_with_reason 
tests/test_env_merge.py::test_superseded_key_value_is_converted_not_dropped 
[gw2] [ 71%] ERROR tests/test_env_merge.py::test_unknown_keys_kept_at_end 
tests/test_env_merge.py::test_explicit_new_key_beats_converted_old_value_in_both_orders 
[gw1] [ 71%] ERROR tests/test_env_merge.py::test_key_known_to_code_but_missing_from_template_is_appended 
tests/test_env_merge.py::test_superseded_migration_is_idempotent 
[gw0] [ 71%] ERROR tests/test_env_merge.py::test_report_never_prints_secret_values 
tests/test_env_merge.py::test_superseded_true_maps_to_auto 
[gw3] [ 72%] ERROR tests/test_env_merge.py::test_superseded_key_value_is_converted_not_dropped 
tests/test_env_merge.py::test_superseded_key_is_absent_from_gui_schema 
[gw2] [ 72%] ERROR tests/test_env_merge.py::test_explicit_new_key_beats_converted_old_value_in_both_orders 
tests/test_env_merge.py::test_missing_old_file_falls_back_to_template 
[gw1] [ 72%] ERROR tests/test_env_merge.py::test_superseded_migration_is_idempotent 
tests/test_env_merge.py::test_real_env_example_round_trips 
[gw0] [ 72%] ERROR tests/test_env_merge.py::test_superseded_true_maps_to_auto 
tests/test_env_merge.py::test_real_env_example_carries_the_new_keys 
[gw3] [ 72%] ERROR tests/test_env_merge.py::test_superseded_key_is_absent_from_gui_schema 
tests/test_env_merge.py::test_real_env_example_migrates_the_superseded_gate_key_in_place 
[gw0] [ 72%] ERROR tests/test_env_merge.py::test_real_env_example_carries_the_new_keys 
tests/test_env_schema.py::test_schema_uses_nearest_section_despite_blank_comment_lines 
[gw2] [ 72%] ERROR tests/test_env_merge.py::test_missing_old_file_falls_back_to_template 
tests/test_env_schema.py::test_schema_includes_multiline_env_calls 
[gw1] [ 73%] ERROR tests/test_env_merge.py::test_real_env_example_round_trips 
tests/test_env_schema.py::test_schema_has_descriptions_for_documented_settings 
[gw3] [ 73%] ERROR tests/test_env_merge.py::test_real_env_example_migrates_the_superseded_gate_key_in_place 
tests/test_env_schema.py::test_schema_excludes_deprecated_compatibility_settings 
[gw2] [ 73%] ERROR tests/test_env_schema.py::test_schema_includes_multiline_env_calls 
[gw1] [ 73%] ERROR tests/test_env_schema.py::test_schema_has_descriptions_for_documented_settings 
tests/test_env_schema.py::test_schema_marks_inherited_defaults 
tests/test_env_schema.py::test_schema_never_leaks_registered_deprecated_keys 
[gw0] [ 73%] ERROR tests/test_env_schema.py::test_schema_uses_nearest_section_despite_blank_comment_lines 
tests/test_env_schema.py::test_schema_keeps_keys_whose_comments_merely_mention_deprecation 
[gw3] [ 73%] ERROR tests/test_env_schema.py::test_schema_excludes_deprecated_compatibility_settings 
tests/test_link_monitor.py::test_any_event_refreshes_last_event_time 
[gw2] [ 74%] ERROR tests/test_env_schema.py::test_schema_never_leaks_registered_deprecated_keys 
[gw1] [ 74%] ERROR tests/test_env_schema.py::test_schema_marks_inherited_defaults 
tests/test_link_monitor.py::test_timeout_probe_ok_refreshes_and_no_alert 
tests/test_link_monitor.py::test_fresh_event_no_probe 
[gw0] [ 74%] ERROR tests/test_env_schema.py::test_schema_keeps_keys_whose_comments_merely_mention_deprecation 
tests/test_link_monitor.py::test_timeout_probe_fail_alerts 
[gw3] [ 74%] ERROR tests/test_link_monitor.py::test_any_event_refreshes_last_event_time 
tests/test_link_monitor.py::test_alert_throttled 
[gw1] [ 74%] ERROR tests/test_link_monitor.py::test_timeout_probe_ok_refreshes_and_no_alert 
[gw2] [ 74%] ERROR tests/test_link_monitor.py::test_fresh_event_no_probe 
tests/test_link_monitor.py::test_disabled_does_nothing 
tests/test_link_monitor.py::test_not_connected_alerts_without_probe 
[gw0] [ 75%] ERROR tests/test_link_monitor.py::test_timeout_probe_fail_alerts 
tests/test_link_monitor.py::test_link_status_fields_and_healthy 
[gw3] [ 75%] ERROR tests/test_link_monitor.py::test_alert_throttled 
tests/test_log_paths.py::test_all_log_paths_live_under_log_dir 
[gw2] [ 75%] ERROR tests/test_link_monitor.py::test_disabled_does_nothing 
tests/test_log_paths.py::test_log_dir_override_moves_every_log 
[gw1] [ 75%] ERROR tests/test_link_monitor.py::test_not_connected_alerts_without_probe 
tests/test_log_paths.py::test_log_dir_defaults_into_project_root_logs 
[gw0] [ 75%] ERROR tests/test_link_monitor.py::test_link_status_fields_and_healthy 
tests/test_log_paths.py::test_deploy_reads_the_configured_json_log_path 
[gw3] [ 75%] ERROR tests/test_log_paths.py::test_all_log_paths_live_under_log_dir 
tests/test_log_paths.py::test_compress_log_setting_is_a_path_not_a_filename 
[gw2] [ 76%] ERROR tests/test_log_paths.py::test_log_dir_override_moves_every_log 
tests/test_log_paths.py::test_deprecated_compress_log_key_is_flagged 
[gw1] [ 76%] ERROR tests/test_log_paths.py::test_log_dir_defaults_into_project_root_logs 
tests/test_logging_sink.py::test_json_lines_parse_and_fields_complete 
[gw0] [ 76%] ERROR tests/test_log_paths.py::test_deploy_reads_the_configured_json_log_path 
tests/test_logging_sink.py::test_long_message_truncated_with_marker 
[gw3] [ 76%] ERROR tests/test_log_paths.py::test_compress_log_setting_is_a_path_not_a_filename 
tests/test_logging_sink.py::test_short_message_not_truncated 
[gw2] [ 76%] ERROR tests/test_log_paths.py::test_deprecated_compress_log_key_is_flagged 
tests/test_logging_sink.py::test_setup_json_sink_writes_file 
[gw1] [ 76%] ERROR tests/test_logging_sink.py::test_json_lines_parse_and_fields_complete 
tests/test_logging_sink.py::test_setup_json_sink_disabled_does_nothing 
[gw0] [ 77%] ERROR tests/test_logging_sink.py::test_long_message_truncated_with_marker 
tests/test_logging_sink.py::test_make_json_formatter_requires_callable 
[gw3] [ 77%] ERROR tests/test_logging_sink.py::test_short_message_not_truncated 
tests/test_plugin_check.py::test_default_facts_yield_no_results 
[gw0] [ 77%] ERROR tests/test_logging_sink.py::test_make_json_formatter_requires_callable 
tests/test_plugin_check.py::test_every_finding_carries_a_fix_hint 
[gw2] [ 77%] ERROR tests/test_logging_sink.py::test_setup_json_sink_writes_file 
tests/test_plugin_check.py::test_compliant_loaded_plugin_yields_no_results 
[gw1] [ 77%] ERROR tests/test_logging_sink.py::test_setup_json_sink_disabled_does_nothing 
tests/test_plugin_check.py::test_total_checks_matches_all_checks 
[gw3] [ 77%] ERROR tests/test_plugin_check.py::test_default_facts_yield_no_results 
tests/test_plugin_check.py::test_run_all_sorts_errors_first 
[gw2] [ 77%] ERROR tests/test_plugin_check.py::test_compliant_loaded_plugin_yields_no_results 
tests/test_plugin_check.py::test_layout_unextracted_archive_names_the_archive 
[gw1] [ 78%] ERROR tests/test_plugin_check.py::test_total_checks_matches_all_checks 
tests/test_plugin_check.py::test_layout_leftover_archive_is_only_a_warning 
[gw0] [ 78%] ERROR tests/test_plugin_check.py::test_every_finding_carries_a_fix_hint 
tests/test_plugin_check.py::test_layout_missing_main_py_is_error 
[gw3] [ 78%] ERROR tests/test_plugin_check.py::test_run_all_sorts_errors_first 
tests/test_plugin_check.py::test_layout_quiet_when_clean 
[gw2] [ 78%] ERROR tests/test_plugin_check.py::test_layout_unextracted_archive_names_the_archive 
tests/test_plugin_check.py::test_load_error_is_error 
[gw1] [ 78%] ERROR tests/test_plugin_check.py::test_layout_leftover_archive_is_only_a_warning 
tests/test_plugin_check.py::test_load_skipped_when_code_was_not_executed 
[gw0] [ 78%] ERROR tests/test_plugin_check.py::test_layout_missing_main_py_is_error 
tests/test_plugin_check.py::test_requirements_missing_is_error_with_pip_command 
[gw3] [ 79%] ERROR tests/test_plugin_check.py::test_layout_quiet_when_clean 
tests/test_plugin_check.py::test_requirements_quiet_when_all_installed 
[gw0] [ 79%] ERROR tests/test_plugin_check.py::test_requirements_missing_is_error_with_pip_command 
tests/test_plugin_check.py::test_tool_declared_by_config_tier_is_quiet 
[gw2] [ 79%] ERROR tests/test_plugin_check.py::test_load_error_is_error 
tests/test_plugin_check.py::test_undeclared_tool_is_error 
[gw1] [ 79%] ERROR tests/test_plugin_check.py::test_load_skipped_when_code_was_not_executed 
tests/test_plugin_check.py::test_tool_declared_by_own_capability_is_quiet 
[gw3] [ 79%] ERROR tests/test_plugin_check.py::test_requirements_quiet_when_all_installed 
tests/test_plugin_check.py::test_tool_undeclared_skipped_when_load_failed 
[gw2] [ 79%] ERROR tests/test_plugin_check.py::test_undeclared_tool_is_error 
tests/test_plugin_check.py::test_provider_missing_quiet_when_names_match 
[gw1] [ 80%] ERROR tests/test_plugin_check.py::test_tool_declared_by_own_capability_is_quiet 
tests/test_plugin_check.py::test_provider_missing_skipped_when_plugin_has_no_tools 
[gw0] [ 80%] ERROR tests/test_plugin_check.py::test_tool_declared_by_config_tier_is_quiet 
tests/test_plugin_check.py::test_provider_typo_is_error_and_suggests_the_real_name 
[gw3] [ 80%] ERROR tests/test_plugin_check.py::test_tool_undeclared_skipped_when_load_failed 
tests/test_plugin_check.py::test_declaration_parse_error_is_error 
[gw2] [ 80%] ERROR tests/test_plugin_check.py::test_provider_missing_quiet_when_names_match 
tests/test_plugin_check.py::test_only_draft_is_error 
[gw1] [ 80%] ERROR tests/test_plugin_check.py::test_provider_missing_skipped_when_plugin_has_no_tools 
tests/test_plugin_check.py::test_reviewed_false_is_error 
[gw0] [ 80%] ERROR tests/test_plugin_check.py::test_provider_typo_is_error_and_suggests_the_real_name 
tests/test_plugin_check.py::test_declaration_quiet_when_reviewed 
[gw3] [ 81%] ERROR tests/test_plugin_check.py::test_declaration_parse_error_is_error 
tests/test_plugin_check.py::test_declaration_quiet_when_key_omitted 
[gw2] [ 81%] ERROR tests/test_plugin_check.py::test_only_draft_is_error 
tests/test_plugin_check.py::test_examples_too_few_is_warn 
[gw1] [ 81%] ERROR tests/test_plugin_check.py::test_reviewed_false_is_error 
tests/test_plugin_check.py::test_examples_count_quiet_at_threshold 
[gw0] [ 81%] ERROR tests/test_plugin_check.py::test_declaration_quiet_when_reviewed 
tests/test_plugin_check.py::test_imperative_examples_are_warned[\u5f53\u7528\u6237\u8be2\u95ee\u5b57\u6570\u65f6\u8c03\u7528\u672c\u5de5\u5177] 
[gw3] [ 81%] ERROR tests/test_plugin_check.py::test_declaration_quiet_when_key_omitted 
tests/test_plugin_check.py::test_imperative_examples_are_warned[\u7528\u4e8e\u7edf\u8ba1\u6587\u5b57\u957f\u5ea6] 
[gw2] [ 81%] ERROR tests/test_plugin_check.py::test_examples_too_few_is_warn 
tests/test_plugin_check.py::test_imperative_examples_are_warned[\u8be5\u5de5\u5177\u8fd4\u56de\u5b57\u6570] 
[gw1] [ 81%] ERROR tests/test_plugin_check.py::test_examples_count_quiet_at_threshold 
tests/test_plugin_check.py::test_question_examples_are_quiet 
[gw0] [ 82%] ERROR tests/test_plugin_check.py::test_imperative_examples_are_warned[\u5f53\u7528\u6237\u8be2\u95ee\u5b57\u6570\u65f6\u8c03\u7528\u672c\u5de5\u5177] 
tests/test_plugin_check.py::test_keyword_leaking_into_another_capability_is_warn 
[gw3] [ 82%] ERROR tests/test_plugin_check.py::test_imperative_examples_are_warned[\u7528\u4e8e\u7edf\u8ba1\u6587\u5b57\u957f\u5ea6] 
tests/test_plugin_check.py::test_keyword_overlapping_its_own_example_is_not_a_finding 
[gw2] [ 82%] ERROR tests/test_plugin_check.py::test_imperative_examples_are_warned[\u8be5\u5de5\u5177\u8fd4\u56de\u5b57\u6570] 
tests/test_plugin_check.py::test_entertainment_reference_declaration_stays_clean 
[gw1] [ 82%] ERROR tests/test_plugin_check.py::test_question_examples_are_quiet 
tests/test_plugin_check.py::test_short_keyword_check_only_flags_the_one_deliberate_override 
[gw0] [ 82%] ERROR tests/test_plugin_check.py::test_keyword_leaking_into_another_capability_is_warn 
tests/test_plugin_check.py::test_short_keyword_is_warn 
[gw3] [ 82%] ERROR tests/test_plugin_check.py::test_keyword_overlapping_its_own_example_is_not_a_finding 
tests/test_plugin_check.py::test_long_keyword_is_quiet 
[gw2] [ 83%] ERROR tests/test_plugin_check.py::test_entertainment_reference_declaration_stays_clean 
tests/test_plugin_check.py::test_keywords_on_tool_with_required_args_is_warn 
[gw1] [ 83%] ERROR tests/test_plugin_check.py::test_short_keyword_check_only_flags_the_one_deliberate_override 
tests/test_plugin_check.py::test_keywords_on_tool_without_required_args_is_quiet 
[gw0] [ 83%] ERROR tests/test_plugin_check.py::test_short_keyword_is_warn 
tests/test_plugin_check.py::test_no_keywords_means_nothing_to_check 
[gw3] [ 83%] ERROR tests/test_plugin_check.py::test_long_keyword_is_quiet 
tests/test_plugin_check.py::test_separation_spread_below_threshold_is_warn 
[gw0] [ 83%] ERROR tests/test_plugin_check.py::test_no_keywords_means_nothing_to_check 
tests/test_plugin_check.py::test_separation_skipped_without_measurements 
[gw2] [ 83%] ERROR tests/test_plugin_check.py::test_keywords_on_tool_with_required_args_is_warn 
tests/test_plugin_check.py::test_negative_sample_margin_below_zero_is_warn 
[gw1] [ 84%] ERROR tests/test_plugin_check.py::test_keywords_on_tool_without_required_args_is_quiet 
tests/test_plugin_check.py::test_separation_quiet_when_healthy 
[gw3] [ 84%] ERROR tests/test_plugin_check.py::test_separation_spread_below_threshold_is_warn 
tests/test_plugin_check.py::test_capability_id_collision_is_info 
[gw2] [ 84%] ERROR tests/test_plugin_check.py::test_negative_sample_margin_below_zero_is_warn 
tests/test_plugin_check.py::test_same_id_claiming_the_same_tool_is_not_a_collision 
[gw1] [ 84%] ERROR tests/test_plugin_check.py::test_separation_quiet_when_healthy 
tests/test_plugin_check.py::test_url_image_is_warn 
[gw0] [ 84%] ERROR tests/test_plugin_check.py::test_separation_skipped_without_measurements 
tests/test_plugin_check.py::test_tool_claimed_by_another_capability_is_info 
[gw3] [ 84%] ERROR tests/test_plugin_check.py::test_capability_id_collision_is_info 
tests/test_plugin_check.py::test_url_image_quiet_when_absent 
[gw2] [ 85%] ERROR tests/test_plugin_check.py::test_same_id_claiming_the_same_tool_is_not_a_collision 
tests/test_plugin_check.py::test_bare_create_task_is_warn 
[gw1] [ 85%] ERROR tests/test_plugin_check.py::test_url_image_is_warn 
tests/test_plugin_check.py::test_bare_create_task_detail_notes_partial_adoption 
[gw0] [ 85%] ERROR tests/test_plugin_check.py::test_tool_claimed_by_another_capability_is_info 
tests/test_plugin_check.py::test_register_task_only_is_quiet 
[gw3] [ 85%] ERROR tests/test_plugin_check.py::test_url_image_quiet_when_absent 
tests/test_plugin_check.py::test_egress_library_without_declaration_is_warn 
[gw0] [ 85%] ERROR tests/test_plugin_check.py::test_register_task_only_is_quiet 
tests/test_plugin_check.py::test_requirements_parsing_drops_versions_options_and_markers 
[gw2] [ 85%] ERROR tests/test_plugin_check.py::test_bare_create_task_is_warn 
tests/test_plugin_check.py::test_egress_declared_is_quiet 
[gw1] [ 86%] ERROR tests/test_plugin_check.py::test_bare_create_task_detail_notes_partial_adoption 
tests/test_plugin_check.py::test_no_egress_library_is_quiet 
[gw3] [ 86%] ERROR tests/test_plugin_check.py::test_egress_library_without_declaration_is_warn 
tests/test_plugin_check.py::test_requirements_absent_is_empty 
[gw2] [ 86%] ERROR tests/test_plugin_check.py::test_egress_declared_is_quiet 
tests/test_plugin_check.py::test_register_task_wrapping_create_task_on_one_line_is_not_flagged 
[gw0] [ 86%] ERROR tests/test_plugin_check.py::test_requirements_parsing_drops_versions_options_and_markers 
[gw1] [ 86%] ERROR tests/test_plugin_check.py::test_no_egress_library_is_quiet 
tests/test_plugin_check.py::test_literals_are_blanked_before_scanning 
tests/test_plugin_check.py::test_egress_imports_are_detected 
[gw3] [ 86%] ERROR tests/test_plugin_check.py::test_requirements_absent_is_empty 
tests/test_plugin_check.py::test_declared_egress_accepts_tables_and_bare_strings 
[gw2] [ 86%] ERROR tests/test_plugin_check.py::test_register_task_wrapping_create_task_on_one_line_is_not_flagged 
tests/test_plugin_check.py::test_declared_egress_empty_without_the_field 
[gw0] [ 87%] ERROR tests/test_plugin_check.py::test_literals_are_blanked_before_scanning 
tests/test_plugin_check.py::test_draft_only_directory_reports_the_gate 
[gw1] [ 87%] ERROR tests/test_plugin_check.py::test_egress_imports_are_detected 
tests/test_plugin_check.py::test_declaration_is_parsed_through_the_shared_loader 
[gw3] [ 87%] ERROR tests/test_plugin_check.py::test_declared_egress_accepts_tables_and_bare_strings 
tests/test_plugin_check.py::test_to_json_gui_contract 
[gw0] [ 87%] ERROR tests/test_plugin_check.py::test_draft_only_directory_reports_the_gate 
tests/test_plugin_check.py::test_terminal_output_discloses_that_plugin_code_ran 
[gw1] [ 87%] ERROR tests/test_plugin_check.py::test_declaration_is_parsed_through_the_shared_loader 
tests/test_plugin_check.py::test_terminal_output_omits_the_disclosure_when_nothing_ran 
[gw2] [ 87%] ERROR tests/test_plugin_check.py::test_declared_egress_empty_without_the_field 
tests/test_plugin_check.py::test_to_json_carries_no_free_text_from_the_declaration 
[gw3] [ 88%] ERROR tests/test_plugin_check.py::test_to_json_gui_contract 
tests/test_plugin_check.py::test_version_prefix_is_not_doubled[v1.6.4-v1.6.4] 
[gw0] [ 88%] ERROR tests/test_plugin_check.py::test_terminal_output_discloses_that_plugin_code_ran 
tests/test_plugin_check.py::test_version_prefix_is_not_doubled[1.0.0-v1.0.0] 
[gw2] [ 88%] ERROR tests/test_plugin_check.py::test_to_json_carries_no_free_text_from_the_declaration 
tests/test_plugin_check.py::test_tools_without_required_args_are_labelled 
[gw1] [ 88%] ERROR tests/test_plugin_check.py::test_terminal_output_omits_the_disclosure_when_nothing_ran 
tests/test_plugin_check.py::test_version_prefix_is_not_doubled[-] 
[gw3] [ 88%] ERROR tests/test_plugin_check.py::test_version_prefix_is_not_doubled[v1.6.4-v1.6.4] 
tests/test_plugin_check.py::test_command_only_plugin_is_told_it_needs_no_declaration 
[gw0] [ 88%] ERROR tests/test_plugin_check.py::test_version_prefix_is_not_doubled[1.0.0-v1.0.0] 
tests/test_plugin_check.py::test_template_plugin_passes_the_whole_pipeline 
[gw2] [ 89%] ERROR tests/test_plugin_check.py::test_tools_without_required_args_are_labelled 
tests/test_policy.py::test_usage_blocked_when_not_in_mode 
[gw1] [ 89%] ERROR tests/test_plugin_check.py::test_version_prefix_is_not_doubled[-] 
tests/test_policy.py::test_usage_allowed_when_in_mode 
[gw3] [ 89%] ERROR tests/test_plugin_check.py::test_command_only_plugin_is_told_it_needs_no_declaration 
tests/test_policy.py::test_boundary_never_chat_material_in_casual 
[gw0] [ 89%] ERROR tests/test_plugin_check.py::test_template_plugin_passes_the_whole_pipeline 
tests/test_policy.py::test_visibility_restricted_denied_in_casual 
[gw2] [ 89%] ERROR tests/test_policy.py::test_usage_blocked_when_not_in_mode 
tests/test_policy.py::test_visibility_restricted_allowed_in_conflict 
[gw1] [ 89%] ERROR tests/test_policy.py::test_usage_allowed_when_in_mode 
tests/test_policy.py::test_detect_mode_tech_and_recommend 
[gw3] [ 90%] ERROR tests/test_policy.py::test_boundary_never_chat_material_in_casual 
tests/test_policy.py::test_detect_mode_proactive 
[gw0] [ 90%] ERROR tests/test_policy.py::test_visibility_restricted_denied_in_casual 
tests/test_policy.py::test_detect_mode_echo_noise_stays_casual 
[gw2] [ 90%] ERROR tests/test_policy.py::test_visibility_restricted_allowed_in_conflict 
tests/test_policy.py::test_detect_mode_ignore_daily_grumbling_conflict 
[gw1] [ 90%] ERROR tests/test_policy.py::test_detect_mode_tech_and_recommend 
tests/test_policy.py::test_detect_mode_scoring_beats_priority_chain 
[gw3] [ 90%] ERROR tests/test_policy.py::test_detect_mode_proactive 
tests/test_policy.py::test_rank_contextual_blocked_when_unrelated 
[gw0] [ 90%] ERROR tests/test_policy.py::test_detect_mode_echo_noise_stays_casual 
tests/test_policy.py::test_rank_contextual_exempted_by_strong_usage 
[gw2] [ 90%] ERROR tests/test_policy.py::test_detect_mode_ignore_daily_grumbling_conflict 
tests/test_policy.py::test_rank_contextual_exempted_by_trigger_topic 
[gw1] [ 91%] ERROR tests/test_policy.py::test_detect_mode_scoring_beats_priority_chain 
tests/test_policy.py::test_trigger_topic_match_keywords_and_topics 
[gw3] [ 91%] ERROR tests/test_policy.py::test_rank_contextual_blocked_when_unrelated 
tests/test_policy.py::test_rank_memories_attaches_score 
[gw0] [ 91%] ERROR tests/test_policy.py::test_rank_contextual_exempted_by_strong_usage 
tests/test_policy.py::test_rank_places_mode_matched_higher 
[gw2] [ 91%] ERROR tests/test_policy.py::test_rank_contextual_exempted_by_trigger_topic 
tests/test_policy.py::test_split_behavior_constraints 
[gw1] [ 91%] ERROR tests/test_policy.py::test_trigger_topic_match_keywords_and_topics 
tests/test_policy.py::test_validate_candidate_corrects_boundary_mislabel 
[gw3] [ 91%] ERROR tests/test_policy.py::test_rank_memories_attaches_score 
tests/test_policy.py::test_stable_profile_facts_filters_persona 
[gw0] [ 92%] ERROR tests/test_policy.py::test_rank_places_mode_matched_higher 
tests/test_proactive_prompt.py::test_verify_instruction_contains_content_and_rules 
[gw2] [ 92%] ERROR tests/test_policy.py::test_split_behavior_constraints 
tests/test_proactive_prompt.py::test_coldstart_instruction_contains_topic 
[gw1] [ 92%] ERROR tests/test_policy.py::test_validate_candidate_corrects_boundary_mislabel 
tests/test_proactive_prompt.py::test_common_rules_present_in_both 
[gw3] [ 92%] ERROR tests/test_policy.py::test_stable_profile_facts_filters_persona 
tests/test_proactive_prompt.py::test_no_placeholder_left 
[gw0] [ 92%] ERROR tests/test_proactive_prompt.py::test_verify_instruction_contains_content_and_rules 
tests/test_proactive_prompt.py::test_context_role_clause_present 
[gw2] [ 92%] ERROR tests/test_proactive_prompt.py::test_coldstart_instruction_contains_topic 
tests/test_proactive_prompt.py::test_build_instruction_dispatches_by_mode 
[gw1] [ 93%] ERROR tests/test_proactive_prompt.py::test_common_rules_present_in_both 
tests/test_release_layout.py::test_release_excludes_are_parsed_without_stray_quotes 
[gw3] [ 93%] ERROR tests/test_proactive_prompt.py::test_no_placeholder_left 
tests/test_release_layout.py::test_every_user_data_path_is_kept_out_of_the_release 
[gw0] [ 93%] ERROR tests/test_proactive_prompt.py::test_context_role_clause_present 
tests/test_release_layout.py::test_data_dir_is_excluded_everywhere 
[gw2] [ 93%] ERROR tests/test_proactive_prompt.py::test_build_instruction_dispatches_by_mode 
tests/test_release_layout.py::test_release_layout_check_rejects_a_packaged_data_dir 
[gw1] [ 93%] ERROR tests/test_release_layout.py::test_release_excludes_are_parsed_without_stray_quotes 
tests/test_release_layout.py::test_never_migrate_paths_are_excluded_from_release 
[gw3] [ 93%] ERROR tests/test_release_layout.py::test_every_user_data_path_is_kept_out_of_the_release 
tests/test_status_api.py::test_is_loopback_true 
[gw0] [ 94%] ERROR tests/test_release_layout.py::test_data_dir_is_excluded_everywhere 
tests/test_status_api.py::test_is_loopback_false 
[gw1] [ 94%] ERROR tests/test_release_layout.py::test_never_migrate_paths_are_excluded_from_release 
tests/test_status_api.py::test_build_payload_omits_secrets 
[gw2] [ 94%] ERROR tests/test_release_layout.py::test_release_layout_check_rejects_a_packaged_data_dir 
tests/test_status_api.py::test_build_payload_fields_complete 
[gw3] [ 94%] ERROR tests/test_status_api.py::test_is_loopback_true 
tests/test_status_api.py::test_build_payload_accepts_none_link 
[gw0] [ 94%] ERROR tests/test_status_api.py::test_is_loopback_false 
tests/test_status_api.py::test_build_payload_reports_group_count 
[gw2] [ 94%] ERROR tests/test_status_api.py::test_build_payload_fields_complete 
tests/test_status_api.py::test_build_payload_passes_usage_through 
[gw1] [ 95%] ERROR tests/test_status_api.py::test_build_payload_omits_secrets 
tests/test_status_api.py::test_build_payload_usage_defaults_to_none 
[gw3] [ 95%] ERROR tests/test_status_api.py::test_build_payload_accepts_none_link 
tests/test_status_api.py::test_usage_snapshot_shape_carries_no_credentials_or_chat_content 
[gw0] [ 95%] ERROR tests/test_status_api.py::test_build_payload_reports_group_count 
tests/test_stella_home.py::test_env_var_wins 
[gw2] [ 95%] ERROR tests/test_status_api.py::test_build_payload_passes_usage_through 
tests/test_stella_home.py::test_legacy_layout_stays_in_place 
[gw1] [ 95%] ERROR tests/test_status_api.py::test_build_payload_usage_defaults_to_none 
tests/test_stella_home.py::test_legacy_layout_detected_by_database_too 
[gw3] [ 95%] ERROR tests/test_status_api.py::test_usage_snapshot_shape_carries_no_credentials_or_chat_content 
tests/test_stella_home.py::test_default_is_sibling_data_dir_and_not_created 
[gw0] [ 95%] ERROR tests/test_stella_home.py::test_env_var_wins 
tests/test_stella_home.py::test_portable_data_dir_inside_install_is_used 
[gw2] [ 96%] ERROR tests/test_stella_home.py::test_legacy_layout_stays_in_place 
tests/test_stella_home.py::test_portable_mode_loses_to_legacy_layout 
[gw1] [ 96%] ERROR tests/test_stella_home.py::test_legacy_layout_detected_by_database_too 
tests/test_stella_home.py::test_portable_mode_loses_to_pointer 
[gw3] [ 96%] ERROR tests/test_stella_home.py::test_default_is_sibling_data_dir_and_not_created 
tests/test_stella_home.py::test_default_stays_outside_when_no_portable_dir 
[gw0] [ 96%] ERROR tests/test_stella_home.py::test_portable_data_dir_inside_install_is_used 
tests/test_stella_home.py::test_create_writes_pointer_file 
[gw2] [ 96%] ERROR tests/test_stella_home.py::test_portable_mode_loses_to_legacy_layout 
tests/test_stella_home.py::test_pointer_file_is_followed_by_a_fresh_install 
[gw1] [ 96%] ERROR tests/test_stella_home.py::test_portable_mode_loses_to_pointer 
tests/test_stella_home.py::test_pointer_takes_precedence_over_default 
[gw3] [ 97%] ERROR tests/test_stella_home.py::test_default_stays_outside_when_no_portable_dir 
tests/test_stella_home.py::test_broken_pointer_falls_back_without_raising 
[gw0] [ 97%] ERROR tests/test_stella_home.py::test_create_writes_pointer_file 
tests/test_stella_home.py::test_user_data_paths_follow_stella_home 
[gw2] [ 97%] ERROR tests/test_stella_home.py::test_pointer_file_is_followed_by_a_fresh_install 
tests/test_stop_signal.py::test_request_and_detect 
[gw1] [ 97%] ERROR tests/test_stella_home.py::test_pointer_takes_precedence_over_default 
tests/test_stop_signal.py::test_clear_is_idempotent 
[gw3] [ 97%] ERROR tests/test_stella_home.py::test_broken_pointer_falls_back_without_raising 
tests/test_stop_signal.py::test_read_returns_metadata 
[gw0] [ 97%] ERROR tests/test_stella_home.py::test_user_data_paths_follow_stella_home 
tests/test_stop_signal.py::test_read_tolerates_corrupt_file 
[gw2] [ 98%] ERROR tests/test_stop_signal.py::test_request_and_detect 
tests/test_text_similarity.py::test_normalize_text_strips_punctuation_and_case 
[gw1] [ 98%] ERROR tests/test_stop_signal.py::test_clear_is_idempotent 
tests/test_text_similarity.py::test_jaccard_edges 
[gw3] [ 98%] ERROR tests/test_stop_signal.py::test_read_returns_metadata 
tests/test_text_similarity.py::test_is_similar_identical_and_substring 
[gw0] [ 98%] ERROR tests/test_stop_signal.py::test_read_tolerates_corrupt_file 
tests/test_text_similarity.py::test_is_similar_rejects_unrelated 
[gw2] [ 98%] ERROR tests/test_text_similarity.py::test_normalize_text_strips_punctuation_and_case 
tests/test_text_similarity.py::test_is_similar_empty_is_never_similar 
[gw1] [ 98%] ERROR tests/test_text_similarity.py::test_jaccard_edges 
tests/test_text_similarity.py::test_is_similar_threshold_is_configurable 
[gw3] [ 99%] ERROR tests/test_text_similarity.py::test_is_similar_identical_and_substring 
tests/test_text_similarity.py::test_merge_content_prefers_more_complete 
[gw0] [ 99%] ERROR tests/test_text_similarity.py::test_is_similar_rejects_unrelated 
tests/test_text_similarity.py::test_merge_content_joins_distinct 
[gw2] [ 99%] ERROR tests/test_text_similarity.py::test_is_similar_empty_is_never_similar 
tests/test_text_similarity.py::test_merge_content_handles_empty 
[gw1] [ 99%] ERROR tests/test_text_similarity.py::test_is_similar_threshold_is_configurable 
[gw3] [ 99%] ERROR tests/test_text_similarity.py::test_merge_content_prefers_more_complete 
[gw0] [ 99%] ERROR tests/test_text_similarity.py::test_merge_content_joins_distinct 
[gw2] [100%] ERROR tests/test_text_similarity.py::test_merge_content_handles_empty 

==================================== ERRORS ====================================
____________________ ERROR collecting tests/astrbot_compat _____________________
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
<frozen importlib._bootstrap>:1050: in _gcd_import
    ???
<frozen importlib._bootstrap>:1027: in _find_and_load
    ???
<frozen importlib._bootstrap>:1006: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:688: in _load_unlocked
    ???
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/astrbot_compat/conftest.py:15: in <module>
    install_shim()
astrbot_compat/shim.py:467: in install_shim
    _install_events(m["astrbot.api.event"], m["astrbot.api.event.filter"])
astrbot_compat/shim.py:298: in _install_events
    from .events import (
astrbot_compat/events.py:15: in <module>
    from .components import (
astrbot_compat/components.py:23: in <module>
    from nonebot.adapters.onebot.v11 import Message, MessageSegment
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________________ ERROR collecting tests/astrbot_compat _____________________
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
<frozen importlib._bootstrap>:1050: in _gcd_import
    ???
<frozen importlib._bootstrap>:1027: in _find_and_load
    ???
<frozen importlib._bootstrap>:1006: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:688: in _load_unlocked
    ???
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/astrbot_compat/conftest.py:15: in <module>
    install_shim()
astrbot_compat/shim.py:467: in install_shim
    _install_events(m["astrbot.api.event"], m["astrbot.api.event.filter"])
astrbot_compat/shim.py:298: in _install_events
    from .events import (
astrbot_compat/events.py:15: in <module>
    from .components import (
astrbot_compat/components.py:23: in <module>
    from nonebot.adapters.onebot.v11 import Message, MessageSegment
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________________ ERROR collecting tests/astrbot_compat _____________________
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
<frozen importlib._bootstrap>:1050: in _gcd_import
    ???
<frozen importlib._bootstrap>:1027: in _find_and_load
    ???
<frozen importlib._bootstrap>:1006: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:688: in _load_unlocked
    ???
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/astrbot_compat/conftest.py:15: in <module>
    install_shim()
astrbot_compat/shim.py:467: in install_shim
    _install_events(m["astrbot.api.event"], m["astrbot.api.event.filter"])
astrbot_compat/shim.py:298: in _install_events
    from .events import (
astrbot_compat/events.py:15: in <module>
    from .components import (
astrbot_compat/components.py:23: in <module>
    from nonebot.adapters.onebot.v11 import Message, MessageSegment
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________________ ERROR collecting tests/astrbot_compat _____________________
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
<frozen importlib._bootstrap>:1050: in _gcd_import
    ???
<frozen importlib._bootstrap>:1027: in _find_and_load
    ???
<frozen importlib._bootstrap>:1006: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:688: in _load_unlocked
    ???
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/astrbot_compat/conftest.py:15: in <module>
    install_shim()
astrbot_compat/shim.py:467: in install_shim
    _install_events(m["astrbot.api.event"], m["astrbot.api.event.filter"])
astrbot_compat/shim.py:298: in _install_events
    from .events import (
astrbot_compat/events.py:15: in <module>
    from .components import (
astrbot_compat/components.py:23: in <module>
    from nonebot.adapters.onebot.v11 import Message, MessageSegment
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_access_semantics.py ________________
tests/test_access_semantics.py:26: in <module>
    import memory.compressor as compressor
memory/compressor.py:30: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_access_semantics.py ________________
tests/test_access_semantics.py:26: in <module>
    import memory.compressor as compressor
memory/compressor.py:30: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_access_semantics.py ________________
tests/test_access_semantics.py:26: in <module>
    import memory.compressor as compressor
memory/compressor.py:30: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_access_semantics.py ________________
tests/test_access_semantics.py:26: in <module>
    import memory.compressor as compressor
memory/compressor.py:30: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_benchmark_and_log.py _______________
tests/test_benchmark_and_log.py:8: in <module>
    import memory.consolidation_log as cl
memory/consolidation_log.py:9: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_benchmark_and_log.py _______________
tests/test_benchmark_and_log.py:8: in <module>
    import memory.consolidation_log as cl
memory/consolidation_log.py:9: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_benchmark_and_log.py _______________
tests/test_benchmark_and_log.py:8: in <module>
    import memory.consolidation_log as cl
memory/consolidation_log.py:9: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_benchmark_and_log.py _______________
tests/test_benchmark_and_log.py:8: in <module>
    import memory.consolidation_log as cl
memory/consolidation_log.py:9: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_bot_self_source.py ________________
tests/test_bot_self_source.py:16: in <module>
    import memory.consolidator as consolidator_mod
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_bot_self_source.py ________________
tests/test_bot_self_source.py:16: in <module>
    import memory.consolidator as consolidator_mod
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_bot_self_source.py ________________
tests/test_bot_self_source.py:16: in <module>
    import memory.consolidator as consolidator_mod
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_bot_self_source.py ________________
tests/test_bot_self_source.py:16: in <module>
    import memory.consolidator as consolidator_mod
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_candidate_reinforcement.py ____________
tests/test_candidate_reinforcement.py:15: in <module>
    from memory.consolidator import MemoryConsolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_candidate_reinforcement.py ____________
tests/test_candidate_reinforcement.py:15: in <module>
    from memory.consolidator import MemoryConsolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_candidate_reinforcement.py ____________
tests/test_candidate_reinforcement.py:15: in <module>
    from memory.consolidator import MemoryConsolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_candidate_reinforcement.py ____________
tests/test_candidate_reinforcement.py:15: in <module>
    from memory.consolidator import MemoryConsolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_compressor.py ___________________
tests/test_compressor.py:17: in <module>
    import memory.compressor as compressor
memory/compressor.py:30: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_compressor.py ___________________
tests/test_compressor.py:17: in <module>
    import memory.compressor as compressor
memory/compressor.py:30: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_compressor.py ___________________
tests/test_compressor.py:17: in <module>
    import memory.compressor as compressor
memory/compressor.py:30: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_compressor.py ___________________
tests/test_compressor.py:17: in <module>
    import memory.compressor as compressor
memory/compressor.py:30: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_consolidator_core.py _______________
tests/test_consolidator_core.py:18: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_consolidator_core.py _______________
tests/test_consolidator_core.py:18: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_consolidator_core.py _______________
tests/test_consolidator_core.py:18: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_consolidator_core.py _______________
tests/test_consolidator_core.py:18: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_context_tail.py __________________
tests/test_context_tail.py:18: in <module>
    import memory.pre_processors as pre_processors_mod
memory/pre_processors.py:20: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_context_tail.py __________________
tests/test_context_tail.py:18: in <module>
    import memory.pre_processors as pre_processors_mod
memory/pre_processors.py:20: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_context_tail.py __________________
tests/test_context_tail.py:18: in <module>
    import memory.pre_processors as pre_processors_mod
memory/pre_processors.py:20: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_context_tail.py __________________
tests/test_context_tail.py:18: in <module>
    import memory.pre_processors as pre_processors_mod
memory/pre_processors.py:20: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_cost_gates.py ___________________
tests/test_cost_gates.py:21: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_cost_gates.py ___________________
tests/test_cost_gates.py:21: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_cost_gates.py ___________________
tests/test_cost_gates.py:21: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_cost_gates.py ___________________
tests/test_cost_gates.py:21: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_____________ ERROR collecting tests/test_cross_user_isolation.py ______________
tests/test_cross_user_isolation.py:15: in <module>
    from memory.compressor import MemoryCompressor
memory/compressor.py:30: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_____________ ERROR collecting tests/test_cross_user_isolation.py ______________
tests/test_cross_user_isolation.py:15: in <module>
    from memory.compressor import MemoryCompressor
memory/compressor.py:30: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_____________ ERROR collecting tests/test_cross_user_isolation.py ______________
tests/test_cross_user_isolation.py:15: in <module>
    from memory.compressor import MemoryCompressor
memory/compressor.py:30: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_____________ ERROR collecting tests/test_cross_user_isolation.py ______________
tests/test_cross_user_isolation.py:15: in <module>
    from memory.compressor import MemoryCompressor
memory/compressor.py:30: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_db_cleaner.py ___________________
tests/test_db_cleaner.py:14: in <module>
    import memory.db_cleaner as db_cleaner
memory/db_cleaner.py:16: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_db_cleaner.py ___________________
tests/test_db_cleaner.py:14: in <module>
    import memory.db_cleaner as db_cleaner
memory/db_cleaner.py:16: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_db_cleaner.py ___________________
tests/test_db_cleaner.py:14: in <module>
    import memory.db_cleaner as db_cleaner
memory/db_cleaner.py:16: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_db_cleaner.py ___________________
tests/test_db_cleaner.py:14: in <module>
    import memory.db_cleaner as db_cleaner
memory/db_cleaner.py:16: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_deploy_cli.py ___________________
tests/test_deploy_cli.py:15: in <module>
    from deploy import __main__ as deploy_main
deploy/__main__.py:29: in <module>
    from . import checks, env_merge, env_schema, migrate, probe, process, report
deploy/probe.py:51: in <module>
    from memory.schema import SCHEMA_VERSION
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_deploy_cli.py ___________________
tests/test_deploy_cli.py:15: in <module>
    from deploy import __main__ as deploy_main
deploy/__main__.py:29: in <module>
    from . import checks, env_merge, env_schema, migrate, probe, process, report
deploy/probe.py:51: in <module>
    from memory.schema import SCHEMA_VERSION
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_deploy_cli.py ___________________
tests/test_deploy_cli.py:15: in <module>
    from deploy import __main__ as deploy_main
deploy/__main__.py:29: in <module>
    from . import checks, env_merge, env_schema, migrate, probe, process, report
deploy/probe.py:51: in <module>
    from memory.schema import SCHEMA_VERSION
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_deploy_cli.py ___________________
tests/test_deploy_cli.py:15: in <module>
    from deploy import __main__ as deploy_main
deploy/__main__.py:29: in <module>
    from . import checks, env_merge, env_schema, migrate, probe, process, report
deploy/probe.py:51: in <module>
    from memory.schema import SCHEMA_VERSION
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_deploy_init.py __________________
tests/test_deploy_init.py:18: in <module>
    from deploy.init_wizard import (
deploy/init_wizard.py:35: in <module>
    from .probe import fetch_loaded_models
deploy/probe.py:51: in <module>
    from memory.schema import SCHEMA_VERSION
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_deploy_init.py __________________
tests/test_deploy_init.py:18: in <module>
    from deploy.init_wizard import (
deploy/init_wizard.py:35: in <module>
    from .probe import fetch_loaded_models
deploy/probe.py:51: in <module>
    from memory.schema import SCHEMA_VERSION
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_deploy_init.py __________________
tests/test_deploy_init.py:18: in <module>
    from deploy.init_wizard import (
deploy/init_wizard.py:35: in <module>
    from .probe import fetch_loaded_models
deploy/probe.py:51: in <module>
    from memory.schema import SCHEMA_VERSION
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_deploy_init.py __________________
tests/test_deploy_init.py:18: in <module>
    from deploy.init_wizard import (
deploy/init_wizard.py:35: in <module>
    from .probe import fetch_loaded_models
deploy/probe.py:51: in <module>
    from memory.schema import SCHEMA_VERSION
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_deploy_migrate.py _________________
tests/test_deploy_migrate.py:20: in <module>
    from tests.test_migrations import build_legacy_v5_db
<frozen importlib._bootstrap>:1027: in _find_and_load
    ???
<frozen importlib._bootstrap>:1006: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:688: in _load_unlocked
    ???
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/test_migrations.py:21: in <module>
    from memory import migrations, schema
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_deploy_migrate.py _________________
tests/test_deploy_migrate.py:20: in <module>
    from tests.test_migrations import build_legacy_v5_db
<frozen importlib._bootstrap>:1027: in _find_and_load
    ???
<frozen importlib._bootstrap>:1006: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:688: in _load_unlocked
    ???
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/test_migrations.py:21: in <module>
    from memory import migrations, schema
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_deploy_migrate.py _________________
tests/test_deploy_migrate.py:20: in <module>
    from tests.test_migrations import build_legacy_v5_db
<frozen importlib._bootstrap>:1027: in _find_and_load
    ???
<frozen importlib._bootstrap>:1006: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:688: in _load_unlocked
    ???
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/test_migrations.py:21: in <module>
    from memory import migrations, schema
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_deploy_migrate.py _________________
tests/test_deploy_migrate.py:20: in <module>
    from tests.test_migrations import build_legacy_v5_db
<frozen importlib._bootstrap>:1027: in _find_and_load
    ???
<frozen importlib._bootstrap>:1006: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:688: in _load_unlocked
    ???
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/test_migrations.py:21: in <module>
    from memory import migrations, schema
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_deploy_probe.py __________________
tests/test_deploy_probe.py:13: in <module>
    from deploy import probe
deploy/probe.py:51: in <module>
    from memory.schema import SCHEMA_VERSION
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_deploy_probe.py __________________
tests/test_deploy_probe.py:13: in <module>
    from deploy import probe
deploy/probe.py:51: in <module>
    from memory.schema import SCHEMA_VERSION
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_deploy_probe.py __________________
tests/test_deploy_probe.py:13: in <module>
    from deploy import probe
deploy/probe.py:51: in <module>
    from memory.schema import SCHEMA_VERSION
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_deploy_probe.py __________________
tests/test_deploy_probe.py:13: in <module>
    from deploy import probe
deploy/probe.py:51: in <module>
    from memory.schema import SCHEMA_VERSION
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_embeddings.py ___________________
tests/test_embeddings.py:15: in <module>
    from memory.embeddings import EmbeddingService, cosine_similarity, normalize
memory/embeddings.py:40: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_embeddings.py ___________________
tests/test_embeddings.py:15: in <module>
    from memory.embeddings import EmbeddingService, cosine_similarity, normalize
memory/embeddings.py:40: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_embeddings.py ___________________
tests/test_embeddings.py:15: in <module>
    from memory.embeddings import EmbeddingService, cosine_similarity, normalize
memory/embeddings.py:40: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_embeddings.py ___________________
tests/test_embeddings.py:15: in <module>
    from memory.embeddings import EmbeddingService, cosine_similarity, normalize
memory/embeddings.py:40: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_full_workflow.py _________________
tests/test_full_workflow.py:24: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_full_workflow.py _________________
tests/test_full_workflow.py:24: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_full_workflow.py _________________
tests/test_full_workflow.py:24: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_full_workflow.py _________________
tests/test_full_workflow.py:24: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_graceful_shutdown.py _______________
tests/test_graceful_shutdown.py:14: in <module>
    from core.shutdown import wait_for_tasks
core/shutdown.py:15: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_graceful_shutdown.py _______________
tests/test_graceful_shutdown.py:14: in <module>
    from core.shutdown import wait_for_tasks
core/shutdown.py:15: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_graceful_shutdown.py _______________
tests/test_graceful_shutdown.py:14: in <module>
    from core.shutdown import wait_for_tasks
core/shutdown.py:15: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_graceful_shutdown.py _______________
tests/test_graceful_shutdown.py:14: in <module>
    from core.shutdown import wait_for_tasks
core/shutdown.py:15: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_llm_compat.py ___________________
tests/test_llm_compat.py:19: in <module>
    import core.llm.compat as compat
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_llm_compat.py ___________________
tests/test_llm_compat.py:19: in <module>
    import core.llm.compat as compat
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_llm_compat.py ___________________
tests/test_llm_compat.py:19: in <module>
    import core.llm.compat as compat
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_llm_compat.py ___________________
tests/test_llm_compat.py:19: in <module>
    import core.llm.compat as compat
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_llm_registry.py __________________
tests/test_llm_registry.py:29: in <module>
    import core.llm.registry as registry
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_llm_registry.py __________________
tests/test_llm_registry.py:29: in <module>
    import core.llm.registry as registry
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_llm_registry.py __________________
tests/test_llm_registry.py:29: in <module>
    import core.llm.registry as registry
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_llm_registry.py __________________
tests/test_llm_registry.py:29: in <module>
    import core.llm.registry as registry
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________________ ERROR collecting tests/test_lm_studio.py ___________________
tests/test_lm_studio.py:16: in <module>
    from core.llm.lm_studio import LMStudioBackend
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________________ ERROR collecting tests/test_lm_studio.py ___________________
tests/test_lm_studio.py:16: in <module>
    from core.llm.lm_studio import LMStudioBackend
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________________ ERROR collecting tests/test_lm_studio.py ___________________
tests/test_lm_studio.py:16: in <module>
    from core.llm.lm_studio import LMStudioBackend
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________________ ERROR collecting tests/test_lm_studio.py ___________________
tests/test_lm_studio.py:16: in <module>
    from core.llm.lm_studio import LMStudioBackend
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_memory_manager.py _________________
tests/test_memory_manager.py:16: in <module>
    import memory.memory_manager as memory_manager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_memory_manager.py _________________
tests/test_memory_manager.py:16: in <module>
    import memory.memory_manager as memory_manager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_memory_manager.py _________________
tests/test_memory_manager.py:16: in <module>
    import memory.memory_manager as memory_manager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_memory_manager.py _________________
tests/test_memory_manager.py:16: in <module>
    import memory.memory_manager as memory_manager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_memory_manager_fts_sync.py ____________
tests/test_memory_manager_fts_sync.py:11: in <module>
    import memory.memory_manager as memory_manager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_memory_manager_fts_sync.py ____________
tests/test_memory_manager_fts_sync.py:11: in <module>
    import memory.memory_manager as memory_manager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_memory_manager_fts_sync.py ____________
tests/test_memory_manager_fts_sync.py:11: in <module>
    import memory.memory_manager as memory_manager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_memory_manager_fts_sync.py ____________
tests/test_memory_manager_fts_sync.py:11: in <module>
    import memory.memory_manager as memory_manager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_memory_manager_v2.py _______________
tests/test_memory_manager_v2.py:9: in <module>
    import memory.memory_manager as memory_manager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_memory_manager_v2.py _______________
tests/test_memory_manager_v2.py:9: in <module>
    import memory.memory_manager as memory_manager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_memory_manager_v2.py _______________
tests/test_memory_manager_v2.py:9: in <module>
    import memory.memory_manager as memory_manager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_memory_manager_v2.py _______________
tests/test_memory_manager_v2.py:9: in <module>
    import memory.memory_manager as memory_manager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________ ERROR collecting tests/test_memory_promotion_deadlock.py ___________
tests/test_memory_promotion_deadlock.py:27: in <module>
    from memory.memory_manager import MemoryManager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________ ERROR collecting tests/test_memory_promotion_deadlock.py ___________
tests/test_memory_promotion_deadlock.py:27: in <module>
    from memory.memory_manager import MemoryManager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________ ERROR collecting tests/test_memory_promotion_deadlock.py ___________
tests/test_memory_promotion_deadlock.py:27: in <module>
    from memory.memory_manager import MemoryManager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________ ERROR collecting tests/test_memory_promotion_deadlock.py ___________
tests/test_memory_promotion_deadlock.py:27: in <module>
    from memory.memory_manager import MemoryManager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_migrations.py ___________________
tests/test_migrations.py:21: in <module>
    from memory import migrations, schema
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_migrations.py ___________________
tests/test_migrations.py:21: in <module>
    from memory import migrations, schema
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_migrations.py ___________________
tests/test_migrations.py:21: in <module>
    from memory import migrations, schema
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_migrations.py ___________________
tests/test_migrations.py:21: in <module>
    from memory import migrations, schema
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_openai_contract.py ________________
tests/test_openai_contract.py:31: in <module>
    import core.llm.compat as compat
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_openai_contract.py ________________
tests/test_openai_contract.py:31: in <module>
    import core.llm.compat as compat
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_openai_contract.py ________________
tests/test_openai_contract.py:31: in <module>
    import core.llm.compat as compat
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_openai_contract.py ________________
tests/test_openai_contract.py:31: in <module>
    import core.llm.compat as compat
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_pipeline_compose.py ________________
tests/test_pipeline_compose.py:11: in <module>
    from core.pipeline import _compose_prompt
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_pipeline_compose.py ________________
tests/test_pipeline_compose.py:11: in <module>
    from core.pipeline import _compose_prompt
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_pipeline_compose.py ________________
tests/test_pipeline_compose.py:11: in <module>
    from core.pipeline import _compose_prompt
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_pipeline_compose.py ________________
tests/test_pipeline_compose.py:11: in <module>
    from core.pipeline import _compose_prompt
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_proactive_at_flow.py _______________
tests/test_proactive_at_flow.py:12: in <module>
    from memory.proactive import ProactiveController
memory/proactive.py:19: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_proactive_at_flow.py _______________
tests/test_proactive_at_flow.py:12: in <module>
    from memory.proactive import ProactiveController
memory/proactive.py:19: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_proactive_at_flow.py _______________
tests/test_proactive_at_flow.py:12: in <module>
    from memory.proactive import ProactiveController
memory/proactive.py:19: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_proactive_at_flow.py _______________
tests/test_proactive_at_flow.py:12: in <module>
    from memory.proactive import ProactiveController
memory/proactive.py:19: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_proactive_gate.py _________________
tests/test_proactive_gate.py:12: in <module>
    from memory import proactive_gate as gate
memory/proactive_gate.py:23: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_proactive_gate.py _________________
tests/test_proactive_gate.py:12: in <module>
    from memory import proactive_gate as gate
memory/proactive_gate.py:23: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_proactive_gate.py _________________
tests/test_proactive_gate.py:12: in <module>
    from memory import proactive_gate as gate
memory/proactive_gate.py:23: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_proactive_gate.py _________________
tests/test_proactive_gate.py:12: in <module>
    from memory import proactive_gate as gate
memory/proactive_gate.py:23: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_proactive_rules.py ________________
tests/test_proactive_rules.py:18: in <module>
    from memory import proactive
memory/proactive.py:19: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_proactive_rules.py ________________
tests/test_proactive_rules.py:18: in <module>
    from memory import proactive
memory/proactive.py:19: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_proactive_rules.py ________________
tests/test_proactive_rules.py:18: in <module>
    from memory import proactive
memory/proactive.py:19: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_proactive_rules.py ________________
tests/test_proactive_rules.py:18: in <module>
    from memory import proactive
memory/proactive.py:19: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_proactive_state.py ________________
tests/test_proactive_state.py:14: in <module>
    from memory import proactive_state
memory/proactive_state.py:23: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_proactive_state.py ________________
tests/test_proactive_state.py:14: in <module>
    from memory import proactive_state
memory/proactive_state.py:23: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_proactive_state.py ________________
tests/test_proactive_state.py:14: in <module>
    from memory import proactive_state
memory/proactive_state.py:23: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_proactive_state.py ________________
tests/test_proactive_state.py:14: in <module>
    from memory import proactive_state
memory/proactive_state.py:23: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_proactive_target.py ________________
tests/test_proactive_target.py:14: in <module>
    import memory.proactive as proactive
memory/proactive.py:19: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_proactive_target.py ________________
tests/test_proactive_target.py:14: in <module>
    import memory.proactive as proactive
memory/proactive.py:19: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_proactive_target.py ________________
tests/test_proactive_target.py:14: in <module>
    import memory.proactive as proactive
memory/proactive.py:19: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_proactive_target.py ________________
tests/test_proactive_target.py:14: in <module>
    import memory.proactive as proactive
memory/proactive.py:19: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_prompt_builder_v2.py _______________
tests/test_prompt_builder_v2.py:9: in <module>
    import memory.trace as trace
memory/trace.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_prompt_builder_v2.py _______________
tests/test_prompt_builder_v2.py:9: in <module>
    import memory.trace as trace
memory/trace.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_prompt_builder_v2.py _______________
tests/test_prompt_builder_v2.py:9: in <module>
    import memory.trace as trace
memory/trace.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_prompt_builder_v2.py _______________
tests/test_prompt_builder_v2.py:9: in <module>
    import memory.trace as trace
memory/trace.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
______________ ERROR collecting tests/test_prompt_cache_prefix.py ______________
tests/test_prompt_cache_prefix.py:21: in <module>
    from memory.session_compact import COMPACT_PROMPT, build_compact_prompt
memory/session_compact.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
______________ ERROR collecting tests/test_prompt_cache_prefix.py ______________
tests/test_prompt_cache_prefix.py:21: in <module>
    from memory.session_compact import COMPACT_PROMPT, build_compact_prompt
memory/session_compact.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
______________ ERROR collecting tests/test_prompt_cache_prefix.py ______________
tests/test_prompt_cache_prefix.py:21: in <module>
    from memory.session_compact import COMPACT_PROMPT, build_compact_prompt
memory/session_compact.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
______________ ERROR collecting tests/test_prompt_cache_prefix.py ______________
tests/test_prompt_cache_prefix.py:21: in <module>
    from memory.session_compact import COMPACT_PROMPT, build_compact_prompt
memory/session_compact.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_rag_switches.py __________________
tests/test_rag_switches.py:9: in <module>
    import memory.retriever as retriever
memory/retriever.py:51: in <module>
    from memory.timeutil import log_sqlite_error
memory/timeutil.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_rag_switches.py __________________
tests/test_rag_switches.py:9: in <module>
    import memory.retriever as retriever
memory/retriever.py:51: in <module>
    from memory.timeutil import log_sqlite_error
memory/timeutil.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_rag_switches.py __________________
tests/test_rag_switches.py:9: in <module>
    import memory.retriever as retriever
memory/retriever.py:51: in <module>
    from memory.timeutil import log_sqlite_error
memory/timeutil.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_________________ ERROR collecting tests/test_rag_switches.py __________________
tests/test_rag_switches.py:9: in <module>
    import memory.retriever as retriever
memory/retriever.py:51: in <module>
    from memory.timeutil import log_sqlite_error
memory/timeutil.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_reply_detection.py ________________
tests/test_reply_detection.py:20: in <module>
    import memory.proactive_target as pt
memory/proactive_target.py:25: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_reply_detection.py ________________
tests/test_reply_detection.py:20: in <module>
    import memory.proactive_target as pt
memory/proactive_target.py:25: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_reply_detection.py ________________
tests/test_reply_detection.py:20: in <module>
    import memory.proactive_target as pt
memory/proactive_target.py:25: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_reply_detection.py ________________
tests/test_reply_detection.py:20: in <module>
    import memory.proactive_target as pt
memory/proactive_target.py:25: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_retrieval_v2_and_schema.py ____________
tests/test_retrieval_v2_and_schema.py:9: in <module>
    import memory.retrieval_v2 as retrieval_v2
memory/retrieval_v2.py:25: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_retrieval_v2_and_schema.py ____________
tests/test_retrieval_v2_and_schema.py:9: in <module>
    import memory.retrieval_v2 as retrieval_v2
memory/retrieval_v2.py:25: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_retrieval_v2_and_schema.py ____________
tests/test_retrieval_v2_and_schema.py:9: in <module>
    import memory.retrieval_v2 as retrieval_v2
memory/retrieval_v2.py:25: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_retrieval_v2_and_schema.py ____________
tests/test_retrieval_v2_and_schema.py:9: in <module>
    import memory.retrieval_v2 as retrieval_v2
memory/retrieval_v2.py:25: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________________ ERROR collecting tests/test_retriever.py ___________________
tests/test_retriever.py:17: in <module>
    import memory.retriever as retriever
memory/retriever.py:51: in <module>
    from memory.timeutil import log_sqlite_error
memory/timeutil.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________________ ERROR collecting tests/test_retriever.py ___________________
tests/test_retriever.py:17: in <module>
    import memory.retriever as retriever
memory/retriever.py:51: in <module>
    from memory.timeutil import log_sqlite_error
memory/timeutil.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________________ ERROR collecting tests/test_retriever.py ___________________
tests/test_retriever.py:17: in <module>
    import memory.retriever as retriever
memory/retriever.py:51: in <module>
    from memory.timeutil import log_sqlite_error
memory/timeutil.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________________ ERROR collecting tests/test_retriever.py ___________________
tests/test_retriever.py:17: in <module>
    import memory.retriever as retriever
memory/retriever.py:51: in <module>
    from memory.timeutil import log_sqlite_error
memory/timeutil.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_____________ ERROR collecting tests/test_scheduler_concurrency.py _____________
tests/test_scheduler_concurrency.py:24: in <module>
    import core.llm.registry as registry
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_____________ ERROR collecting tests/test_scheduler_concurrency.py _____________
tests/test_scheduler_concurrency.py:24: in <module>
    import core.llm.registry as registry
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_____________ ERROR collecting tests/test_scheduler_concurrency.py _____________
tests/test_scheduler_concurrency.py:24: in <module>
    import core.llm.registry as registry
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_____________ ERROR collecting tests/test_scheduler_concurrency.py _____________
tests/test_scheduler_concurrency.py:24: in <module>
    import core.llm.registry as registry
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_session_compact.py ________________
tests/test_session_compact.py:14: in <module>
    from memory import session_compact as compact
memory/session_compact.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_session_compact.py ________________
tests/test_session_compact.py:14: in <module>
    from memory import session_compact as compact
memory/session_compact.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_session_compact.py ________________
tests/test_session_compact.py:14: in <module>
    from memory import session_compact as compact
memory/session_compact.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_session_compact.py ________________
tests/test_session_compact.py:14: in <module>
    from memory import session_compact as compact
memory/session_compact.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_session_context.py ________________
tests/test_session_context.py:11: in <module>
    from memory import session_context as sc
memory/session_context.py:26: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_session_context.py ________________
tests/test_session_context.py:11: in <module>
    from memory import session_context as sc
memory/session_context.py:26: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_session_context.py ________________
tests/test_session_context.py:11: in <module>
    from memory import session_context as sc
memory/session_context.py:26: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
________________ ERROR collecting tests/test_session_context.py ________________
tests/test_session_context.py:11: in <module>
    from memory import session_context as sc
memory/session_context.py:26: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_short_term_attribution.py _____________
tests/test_short_term_attribution.py:21: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_short_term_attribution.py _____________
tests/test_short_term_attribution.py:21: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_short_term_attribution.py _____________
tests/test_short_term_attribution.py:21: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________ ERROR collecting tests/test_short_term_attribution.py _____________
tests/test_short_term_attribution.py:21: in <module>
    import memory.consolidator as consolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_source_kind.py __________________
tests/test_source_kind.py:13: in <module>
    from memory.consolidator import MemoryConsolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_source_kind.py __________________
tests/test_source_kind.py:13: in <module>
    from memory.consolidator import MemoryConsolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_source_kind.py __________________
tests/test_source_kind.py:13: in <module>
    from memory.consolidator import MemoryConsolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_source_kind.py __________________
tests/test_source_kind.py:13: in <module>
    from memory.consolidator import MemoryConsolidator
memory/consolidator.py:32: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_space_merge.py __________________
tests/test_space_merge.py:19: in <module>
    from memory import schema, space_merge
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_space_merge.py __________________
tests/test_space_merge.py:19: in <module>
    from memory import schema, space_merge
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_space_merge.py __________________
tests/test_space_merge.py:19: in <module>
    from memory import schema, space_merge
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
__________________ ERROR collecting tests/test_space_merge.py __________________
tests/test_space_merge.py:19: in <module>
    from memory import schema, space_merge
memory/schema.py:51: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________________ ERROR collecting tests/test_spaces.py _____________________
tests/test_spaces.py:13: in <module>
    import nonebot
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________________ ERROR collecting tests/test_spaces.py _____________________
tests/test_spaces.py:13: in <module>
    import nonebot
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________________ ERROR collecting tests/test_spaces.py _____________________
tests/test_spaces.py:13: in <module>
    import nonebot
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____________________ ERROR collecting tests/test_spaces.py _____________________
tests/test_spaces.py:13: in <module>
    import nonebot
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________ ERROR collecting tests/test_time_sensitive_candidates.py ___________
tests/test_time_sensitive_candidates.py:25: in <module>
    from memory.memory_manager import MemoryManager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________ ERROR collecting tests/test_time_sensitive_candidates.py ___________
tests/test_time_sensitive_candidates.py:25: in <module>
    from memory.memory_manager import MemoryManager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________ ERROR collecting tests/test_time_sensitive_candidates.py ___________
tests/test_time_sensitive_candidates.py:25: in <module>
    from memory.memory_manager import MemoryManager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________ ERROR collecting tests/test_time_sensitive_candidates.py ___________
tests/test_time_sensitive_candidates.py:25: in <module>
    from memory.memory_manager import MemoryManager
memory/memory_manager.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________________ ERROR collecting tests/test_timeutil.py ____________________
tests/test_timeutil.py:12: in <module>
    from memory.timeutil import (
memory/timeutil.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________________ ERROR collecting tests/test_timeutil.py ____________________
tests/test_timeutil.py:12: in <module>
    from memory.timeutil import (
memory/timeutil.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________________ ERROR collecting tests/test_timeutil.py ____________________
tests/test_timeutil.py:12: in <module>
    from memory.timeutil import (
memory/timeutil.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
___________________ ERROR collecting tests/test_timeutil.py ____________________
tests/test_timeutil.py:12: in <module>
    from memory.timeutil import (
memory/timeutil.py:24: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_____________________ ERROR collecting tests/test_trace.py _____________________
tests/test_trace.py:14: in <module>
    import memory.trace as trace
memory/trace.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_____________________ ERROR collecting tests/test_trace.py _____________________
tests/test_trace.py:14: in <module>
    import memory.trace as trace
memory/trace.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_____________________ ERROR collecting tests/test_trace.py _____________________
tests/test_trace.py:14: in <module>
    import memory.trace as trace
memory/trace.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_____________________ ERROR collecting tests/test_trace.py _____________________
tests/test_trace.py:14: in <module>
    import memory.trace as trace
memory/trace.py:27: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_usage_accounting.py ________________
tests/test_usage_accounting.py:22: in <module>
    import core.llm.usage_sink as usage_sink
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_usage_accounting.py ________________
tests/test_usage_accounting.py:22: in <module>
    import core.llm.usage_sink as usage_sink
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_usage_accounting.py ________________
tests/test_usage_accounting.py:22: in <module>
    import core.llm.usage_sink as usage_sink
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
_______________ ERROR collecting tests/test_usage_accounting.py ________________
tests/test_usage_accounting.py:22: in <module>
    import core.llm.usage_sink as usage_sink
core/llm/__init__.py:18: in <module>
    from core.llm.registry import (
core/llm/registry.py:45: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: in _NoCopy
    def __copy__(self) -> _t.Self:
E   AttributeError: module 'typing' has no attribute 'Self'
____ ERROR at setup of test_derived_capability_has_no_examples_or_keywords _____
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b3be4a0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______________ ERROR at setup of test_auto_capability_id_prefix _______________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc3e7e20>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______________ ERROR at setup of test_derives_capability_per_tool ______________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1da3773d0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_description_falls_back_to_tool_name __________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8cf4bdf0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_ ERROR at setup of test_unclaimed_tools_still_derived_alongside_declarations __
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b948040>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______________ ERROR at setup of test_inactive_tools_are_skipped _______________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c5daaa40>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_____________ ERROR at setup of test_input_schema_copied_from_tool _____________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc79cf40>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_____________ ERROR at setup of test_declared_tool_is_not_derived ______________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8cc13790>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________________ ERROR at setup of test_sync_is_idempotent ___________________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159bb71300>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______ ERROR at setup of test_bootstrap_lets_declaration_claim_the_tool _______
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d8a99bd0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______ ERROR at setup of test_bootstrap_with_no_declarations_is_all_auto _______
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3ba10a5600>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____________ ERROR at setup of test_sync_picks_up_newly_added_tools ____________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7accda4c40>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___ ERROR at setup of test_derived_capability_is_registered_but_not_routable ___
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b3e1db0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_bootstrap_reports_routable_count ____________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8cf9f370>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_auto_route_policy_reads_settings ____________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1da3d6e90>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________ ERROR at setup of test_auto_capabilities_route_when_opted_in _________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acccba530>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_build_tool_tasks_one_per_capability __________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8cf064a0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_____________ ERROR at setup of test_build_tool_tasks_empty_route ______________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c6756f50>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____ ERROR at setup of test_build_tool_tasks_uses_user_message_as_objective ____
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15a7b4a740>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____________ ERROR at setup of test_memory_runs_when_gate_disabled _____________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc420dc0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___ ERROR at setup of test_memory_runs_when_gate_enabled_and_route_wants_it ____
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8d41e590>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______________ ERROR at setup of test_route_is_stored_on_context _______________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c64ddb40>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_memory_skipped_when_gate_enabled ____________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15aa268310>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_intent_and_trigger_are_passed_to_router ________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7ad8114940>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_comes_skipped_without_platform_handles _________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d8a99960>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____________ ERROR at setup of test_comes_runs_and_fills_summaries _____________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8cfcd810>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______________ ERROR at setup of test_comes_skipped_when_disabled ______________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15a9ec6920>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_comes_skipped_when_compat_disabled ___________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acca0e320>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_memory_failure_does_not_kill_comes ___________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159bb73910>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_comes_failure_does_not_kill_memory ___________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7accc56c50>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____________ ERROR at setup of test_both_branches_run_concurrently _____________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c6434fa0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_failed_results_do_not_reach_the_prompt _________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b989bc5b0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_no_jobs_returns_context_unchanged ___________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b9b6dea70>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_router_entry_failure_degrades_to_memory ________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d817ba30>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______ ERROR at setup of test_register_uses_priority_below_build_context _______
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15aa4073a0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________ ERROR at setup of test_registry_singleton_is_used_by_default _________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7ad8bc8c10>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______ ERROR at setup of test_provider_priority_falls_back_on_bad_value _______
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8d4fbfd0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_skips_providers_without_tool_name ___________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c629cb20>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_loads_capability_with_string_providers _________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15a9f0fe20>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_loads_table_providers_with_priority __________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7accd42ec0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________ ERROR at setup of test_missing_capability_section_is_skipped _________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7adafdb0d0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_broken_toml_is_skipped_not_raised ___________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159bb732e0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______________ ERROR at setup of test_skips_capability_without_id ______________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8cfce1d0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______________ ERROR at setup of test_accepts_single_table_form _______________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c655e8c0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_non_list_capability_section_is_skipped _________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8cf053f0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___ ERROR at setup of test_load_directory_merges_all_files_deterministically ___
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d8b2dd50>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____________ ERROR at setup of test_missing_directory_returns_zero _____________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15aa062830>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_____________ ERROR at setup of test_empty_directory_returns_zero ______________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc90f730>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_resolve_tools_skips_inactive_tools ___________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3ba10a5750>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_resolve_tools_reports_unsupported_kind _________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d850dff0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_input_schema_is_kept_only_when_dict __________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15a71c93c0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________ ERROR at setup of test_resolve_tools_reports_missing_plugins _________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc772c50>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______ ERROR at setup of test_can_direct_call_only_for_single_no_arg_tool ______
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8d41ffd0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______________ ERROR at setup of test_disabled_comes_fails_fast _______________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c5f66aa0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______________ ERROR at setup of test_missing_event_fails_fast ________________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15aa06f8b0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______________ ERROR at setup of test_unknown_capability_fails ________________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7adaf3d0f0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______________ ERROR at setup of test_all_tools_unavailable_fails ______________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c62ac6d0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_capability_without_provider_fails ___________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b98958730>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______________ ERROR at setup of test_direct_call_skips_the_model ______________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15aa4062f0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______________ ERROR at setup of test_direct_call_can_be_disabled ______________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7ad87d3640>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_only_scoped_tools_reach_the_model ___________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c6437460>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________ ERROR at setup of test_direct_call_passes_task_input_as_args _________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8cbaba00>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___ ERROR at setup of test_stella_persona_and_chat_context_never_reach_comes ___
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15a9f0feb0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_____________ ERROR at setup of test_objective_carries_known_slots _____________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7adb6eb010>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_agent_completion_becomes_summary ____________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c6689ab0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______________ ERROR at setup of test_no_tool_called_is_failed ________________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8cf999c0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________________ ERROR at setup of test_tool_error_is_failed __________________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15ab8fc1f0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_____________ ERROR at setup of test_partial_when_some_tools_fail ______________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7accc47880>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____________ ERROR at setup of test_execute_all_empty_returns_empty ____________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b9fae60>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_execute_all_returns_in_input_order ___________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc3d53f0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_____________ ERROR at setup of test_timeout_is_failed_not_raised ______________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8cf48d00>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_llm_disabled_is_failed_not_raised ___________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d8996080>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_execute_all_survives_a_broken_task ___________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b9b6ddea0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_failure_is_recorded_on_the_provider __________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d8178130>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_success_clears_recorded_failures ____________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b7f9780>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_uncalled_providers_are_not_charged ___________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7ae08b6890>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________ ERROR at setup of test_is_no_return_matches_internal_marker __________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b9b7c9330>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_truncate_adds_ellipsis_only_when_needed ________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c62ee200>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______ ERROR at setup of test_backed_off_provider_is_skipped_next_time ________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15a9fe7fa0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________ ERROR at setup of test_is_error_matches_execute_tool_prefix __________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7ad81826e0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______________ ERROR at setup of test_multiple_outputs_are_listed ______________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159ba30c10>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_errors_and_no_return_are_dropped ____________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7adafc1870>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________ ERROR at setup of test_single_output_has_no_tool_name_prefix _________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c6353880>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______ ERROR at setup of test_truncate_unlimited_when_limit_non_positive _______
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b9895e0e0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______________ ERROR at setup of test_all_unusable_returns_empty _______________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8d3c6aa0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_budget_is_split_across_multiple_outputs ________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c62ef910>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_completion_text_wins_when_present ___________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b3a6500>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______ ERROR at setup of test_falls_back_to_outputs_when_completion_empty ______
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7accd40e80>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_____________ ERROR at setup of test_stringify_handles_non_strings _____________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3ba09e0e50>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____________ ERROR at setup of test_everything_empty_returns_empty _____________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d80cfeb0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_____ ERROR at setup of test_completion_echoing_internal_marker_is_ignored _____
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15ab90dd20>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_completion_is_truncated_to_budget ___________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7accd40a60>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_plugin_declaration_is_loaded_and_tagged ________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c5f01c00>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________ ERROR at setup of test_reviewed_false_blocks_the_whole_file __________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b7f9600>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________________ ERROR at setup of test_reviewed_true_is_loaded ________________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc3e4100>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_declaration_filename_must_be_exact ___________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3ba10bb0a0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_failed_plugin_declaration_is_not_loaded ________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d816fac0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______ ERROR at setup of test_missing_reviewed_key_is_treated_as_reviewed ______
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8d5a28c0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_____ ERROR at setup of test_deactivated_plugin_declaration_is_not_loaded ______
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b45ee00>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______ ERROR at setup of test_broken_plugin_toml_does_not_stop_the_tier _______
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc989c60>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_switch_off_skips_the_whole_plugin_tier _________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1da3d5ff0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_ ERROR at setup of test_user_override_under_a_different_id_still_shadows_the_plugin _
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b98f19de0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_user_tier_wins_over_factory_and_plugin _________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b7f2680>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___ ERROR at setup of test_plugin_wins_when_no_config_tier_declares_the_tool ___
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7accc46530>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______ ERROR at setup of test_factory_tier_is_not_shadowed_by_a_user_file ______
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d850d690>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_identical_config_dirs_are_read_once __________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b9b7cad70>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______________ ERROR at setup of test_config_dirs_are_user_first _______________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15a9f0fc10>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___ ERROR at setup of test_prototype_texts_includes_examples_and_description ___
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7ad818c460>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___ ERROR at setup of test_enabled_providers_is_stable_within_same_priority ____
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15a9fe7c10>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____________ ERROR at setup of test_disabled_providers_are_excluded ____________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc79e110>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______ ERROR at setup of test_enabled_providers_sorted_by_priority_desc _______
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3ba09e3be0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_prototype_texts_drops_blank_entries __________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c628c7f0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_register_merges_instead_of_overwriting _________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8d057c70>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________ ERROR at setup of test_is_auto_detects_derived_capabilities __________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c62ef220>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__ ERROR at setup of test_register_fills_empty_fields_from_later_registration __
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159ba33730>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________ ERROR at setup of test_register_does_not_duplicate_examples __________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc3dcc70>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________ ERROR at setup of test_tool_claim_is_first_come_first_served _________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d80cdf90>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_add_provider_rebinds_capability_id ___________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8d22bc10>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___ ERROR at setup of test_add_provider_to_unknown_capability_returns_false ____
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc989c60>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______ ERROR at setup of test_add_provider_rejects_duplicate_provider_id _______
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b3e0c40>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___ ERROR at setup of test_register_merge_lets_declaration_win_route_enabled ___
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc771420>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_routable_excludes_route_disabled ____________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b828130>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______ ERROR at setup of test_routable_requires_provider_and_prototype ________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d80b95a0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______ ERROR at setup of test_claimed_by_returns_none_for_unknown_tool ________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8cc59870>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__ ERROR at setup of test_register_merge_keeps_disabled_on_idempotent_resync ___
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c5e97dc0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____________ ERROR at setup of test_version_bumps_on_every_mutation ____________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b9bac1ae0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________________ ERROR at setup of test_all_and_ids_are_sorted _________________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7ad8b23af0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________________ ERROR at setup of test_clear_resets_claims_too ________________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b3a2680>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____ ERROR at setup of test_unregister_releases_providers_added_afterwards _____
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c5f258d0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__ ERROR at setup of test_unregister_unknown_returns_false_and_keeps_version ___
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3ba10b92d0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_unregister_releases_claimed_tools ___________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7ad87d2a10>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_unregister_only_releases_its_own_tools _________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159ba30dc0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_release_tool_frees_a_single_claim ___________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d850d5d0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
______ ERROR at setup of test_package_does_not_shadow_registry_submodule _______
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc4225c0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_____________ ERROR at setup of test_builtin_cases_pass_rules_only _____________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b3e2680>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____ ERROR at setup of test_module_singleton_is_shared_across_import_paths _____
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b98959e40>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
__________ ERROR at setup of test_builtin_cases_cover_the_known_traps __________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1c5e810f0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_____ ERROR at setup of test_gate_safe_requires_zero_memory_false_negative _____
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3ba09e33a0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
___________ ERROR at setup of test_gate_safe_ignores_low_cost_errors ___________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7acc442590>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______________ ERROR at setup of test_capability_miss_detected ________________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f159b3a21a0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________ ERROR at setup of test_capability_not_checked_when_unspecified ________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1d816dc90>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
________________ ERROR at setup of test_render_on_clean_report _________________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b8d3c1000>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_______________ ERROR at setup of test_by_level_counts_decisions _______________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f7accce51b0>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
____________ ERROR at setup of test_render_lists_high_cost_failures ____________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f15a716c820>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/__init__.py:201: in <module>
    from .on import CommandGroup as CommandGroup
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/plugin/on.py:21: in <module>
    from nonebot.rule import (
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/rule.py:33: in <module>
    from pygtrie import CharTrie
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:80: in <module>
    class _NoCopy:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    class _NoCopy:
        """Object which returns itself when copying."""
        __slots__ = ()
>       def __copy__(self) -> _t.Self:
E       AttributeError: module 'typing' has no attribute 'Self'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pygtrie.py:83: AttributeError
_________________ ERROR at setup of test_load_cases_from_file __________________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa1da377280>

    @pytest.fixture(autouse=True)
    def _force_v1_memory_path(monkeypatch):
        """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
>       import core.pipeline

tests/conftest.py:31: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
core/pipeline.py:17: in <module>
    from nonebot import logger
/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/nonebot/__init__.py:340: in <module>
    from nonebot.plugin import CommandGroup as CommandGroup
