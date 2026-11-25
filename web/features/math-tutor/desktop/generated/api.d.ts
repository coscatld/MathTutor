export interface paths {
    "/api/v2/math-tutor/cycles/{cycle_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Cycle */
        get: operations["get_cycle_api_v2_math_tutor_cycles__cycle_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/backup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Backup Endpoint
         * @description Take one online backup now (VACUUM INTO + manifest) and apply the
         *     retention limit. Failures return a friendly message — never internals.
         */
        post: operations["create_backup_endpoint_api_v2_math_tutor_desktop_backup_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/backup/restore": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Restore Backup Endpoint
         * @description Hold admission until the owned restore reaches a known file/runtime state.
         */
        post: operations["restore_backup_endpoint_api_v2_math_tutor_desktop_backup_restore_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/backup/verify": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Verify Backup Endpoint
         * @description Re-verify one backup (manifest sha256 + size + integrity_check).
         */
        post: operations["verify_backup_endpoint_api_v2_math_tutor_desktop_backup_verify_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/backups": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Backups Endpoint
         * @description Backup inventory (wire contract BackupsList). Newest first; the
         *     service's own statuses annotate corrupt/orphan entries — listing never
         *     deletes anything.
         */
        get: operations["list_backups_endpoint_api_v2_math_tutor_desktop_backups_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/bootstrap": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Bootstrap
         * @description The recorded boot sequence (wire contract BootstrapPayload).
         *
         *     Read-only: while booting, ``phase`` is the current step key; once the
         *     startup hook finishes it becomes "READY" and ``readiness``/``reason``
         *     reflect the final step statuses.
         */
        get: operations["bootstrap_api_v2_math_tutor_desktop_bootstrap_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/conversations/{conversation_id}/documents/{document_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Attach Conversation Document */
        post: operations["attach_conversation_document_api_v2_math_tutor_desktop_conversations__conversation_id__documents__document_id__post"];
        /** Detach Conversation Document */
        delete: operations["detach_conversation_document_api_v2_math_tutor_desktop_conversations__conversation_id__documents__document_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/conversations/{conversation_id}/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Export Conversation Folder */
        get: operations["export_conversation_folder_api_v2_math_tutor_desktop_conversations__conversation_id__export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/conversations/{conversation_id}/resources": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Conversation Resources */
        get: operations["conversation_resources_api_v2_math_tutor_desktop_conversations__conversation_id__resources_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/diagnostics/turns": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Turn Diagnostics
         * @description Persisted turn health and recent turns: structure only, no text.
         */
        get: operations["turn_diagnostics_api_v2_math_tutor_desktop_diagnostics_turns_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/documents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Documents */
        get: operations["list_documents_api_v2_math_tutor_desktop_documents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/documents/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Import Document
         * @description Import one explicitly uploaded file (browser fallback / Electron).
         */
        post: operations["import_document_api_v2_math_tutor_desktop_documents_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/documents/pick": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Pick Document
         * @description Ask the desktop shell for ONE explicit user-picked file, then import.
         *
         *     Returns ``{"status": "cancelled"}`` when the user closes the dialog.
         *     The shell is unreachable → explicit 501 (never a silent scan).
         */
        post: operations["pick_document_api_v2_math_tutor_desktop_documents_pick_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/documents/{document_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Document */
        get: operations["get_document_api_v2_math_tutor_desktop_documents__document_id__get"];
        /**
         * Reparse Document
         * @description Re-run parse + chunk on the stored bytes (same pipeline as import).
         */
        put: operations["reparse_document_api_v2_math_tutor_desktop_documents__document_id__put"];
        post?: never;
        /**
         * Delete Document
         * @description Delete one document through the lifecycle service: soft delete the
         *     row + remove the storage file (status-quo semantics) AND make the
         *     content cleanup real — chunk facts and derived vector/index rows go in
         *     the same breath (Phase 6 round 2, SUBAGENT D).
         */
        delete: operations["delete_document_api_v2_math_tutor_desktop_documents__document_id__delete"];
        options?: never;
        head?: never;
        /** Rename Document */
        patch: operations["rename_document_api_v2_math_tutor_desktop_documents__document_id__patch"];
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/documents/{document_id}/retrieval": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Set Document Retrieval */
        patch: operations["set_document_retrieval_api_v2_math_tutor_desktop_documents__document_id__retrieval_patch"];
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/documents/{document_id}/scope": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Set Document Scope Setting */
        patch: operations["set_document_scope_setting_api_v2_math_tutor_desktop_documents__document_id__scope_patch"];
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/exercise-bank": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Question Bank
         * @description Catalog tree for one stage (default: the learner's stage; none set → all stages).
         */
        get: operations["get_question_bank_api_v2_math_tutor_desktop_exercise_bank_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/exercise-bank/points/{code}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Question Bank Point */
        get: operations["get_question_bank_point_api_v2_math_tutor_desktop_exercise_bank_points__code__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/exploration/configuration": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Configuration */
        get: operations["configuration_api_v2_math_tutor_desktop_exploration_configuration_get"];
        /** Configure */
        put: operations["configure_api_v2_math_tutor_desktop_exploration_configuration_put"];
        post?: never;
        /** Disconnect */
        delete: operations["disconnect_api_v2_math_tutor_desktop_exploration_configuration_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/exploration/inquiries": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Inquiries */
        get: operations["inquiries_api_v2_math_tutor_desktop_exploration_inquiries_get"];
        put?: never;
        /** Create */
        post: operations["create_api_v2_math_tutor_desktop_exploration_inquiries_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/exploration/inquiries/{inquiry_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read */
        get: operations["read_api_v2_math_tutor_desktop_exploration_inquiries__inquiry_id__get"];
        put?: never;
        post?: never;
        /** Delete */
        delete: operations["delete_api_v2_math_tutor_desktop_exploration_inquiries__inquiry_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/exploration/inquiries/{inquiry_id}/explanation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Explanation */
        post: operations["explanation_api_v2_math_tutor_desktop_exploration_inquiries__inquiry_id__explanation_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/exploration/inquiries/{inquiry_id}/organize": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Organize */
        post: operations["organize_api_v2_math_tutor_desktop_exploration_inquiries__inquiry_id__organize_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/exploration/inquiries/{inquiry_id}/reflection": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Reflection */
        put: operations["reflection_api_v2_math_tutor_desktop_exploration_inquiries__inquiry_id__reflection_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/exploration/inquiries/{inquiry_id}/response": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Respond */
        post: operations["respond_api_v2_math_tutor_desktop_exploration_inquiries__inquiry_id__response_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/exploration/library": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Search Library */
        post: operations["search_library_api_v2_math_tutor_desktop_exploration_library_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/initial-assessment": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Initial Assessment */
        get: operations["initial_assessment_api_v2_math_tutor_desktop_initial_assessment_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/initial-assessment/answer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Answer Initial Assessment */
        post: operations["answer_initial_assessment_api_v2_math_tutor_desktop_initial_assessment_answer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/initial-assessment/resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resume Initial Assessment */
        post: operations["resume_initial_assessment_api_v2_math_tutor_desktop_initial_assessment_resume_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/initial-assessment/skip": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Skip Initial Assessment */
        post: operations["skip_initial_assessment_api_v2_math_tutor_desktop_initial_assessment_skip_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/initial-assessment/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start Initial Assessment */
        post: operations["start_initial_assessment_api_v2_math_tutor_desktop_initial_assessment_start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/learning-loop": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Learning Loop */
        get: operations["learning_loop_api_v2_math_tutor_desktop_learning_loop_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/learning-loop/answer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Answer Learning Loop */
        post: operations["answer_learning_loop_api_v2_math_tutor_desktop_learning_loop_answer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/learning-loop/help": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Help Learning Loop */
        post: operations["help_learning_loop_api_v2_math_tutor_desktop_learning_loop_help_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/learning-loop/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start Learning Loop */
        post: operations["start_learning_loop_api_v2_math_tutor_desktop_learning_loop_start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/memory": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Memory */
        get: operations["list_memory_api_v2_math_tutor_desktop_memory_get"];
        put?: never;
        /** Create Memory */
        post: operations["create_memory_api_v2_math_tutor_desktop_memory_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/memory/{memory_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Memory */
        put: operations["update_memory_api_v2_math_tutor_desktop_memory__memory_id__put"];
        post?: never;
        /** Delete Memory */
        delete: operations["delete_memory_api_v2_math_tutor_desktop_memory__memory_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/memory/{memory_id}/confirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Confirm Memory
         * @description MODEL_INFERRED → USER_CONFIRMED — the only legal migration.
         */
        post: operations["confirm_memory_api_v2_math_tutor_desktop_memory__memory_id__confirm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/memory/{memory_id}/retrieval": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Set Memory Retrieval */
        patch: operations["set_memory_retrieval_api_v2_math_tutor_desktop_memory__memory_id__retrieval_patch"];
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/model/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Test Model
         * @description Probe the configured provider (wire contract ModelTestResult).
         *
         *     ``error_kind`` is the five-way classification; ``message`` is friendly
         *     copy by contract — the raw (redacted) provider message never leaves
         *     this router.
         */
        post: operations["test_model_api_v2_math_tutor_desktop_model_test_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/privacy/educational-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Delete Educational History
         * @description Delete the student's educational RESULT facts (attempts,
         *     assessments, evidence, observations, attempt-linked verification logs)
         *     inside one short transaction, then REPLAY the StudentState projection
         *     from the remaining evidence (invariant B — mastery is never zeroed by
         *     hand; whatever the replay yields IS the new state). The session
         *     skeleton (cycles/transitions/problem submissions/tutor actions/offers)
         *     is kept. Destructive — the UI confirms twice before calling. Never
         *     routes through the memory CRUD surface.
         */
        post: operations["delete_educational_history_api_v2_math_tutor_desktop_privacy_educational_history_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/privacy/encryption": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Encryption
         * @description Database encryption mode, any pending change, and whether backups are encrypted.
         */
        get: operations["get_encryption_api_v2_math_tutor_desktop_privacy_encryption_get"];
        /**
         * Put Encryption
         * @description Record the wanted mode; the conversion runs at the next start.
         */
        put: operations["put_encryption_api_v2_math_tutor_desktop_privacy_encryption_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/privacy/encryption/recovery-key": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reveal Recovery Key
         * @description The backup key, shown only on an explicit request so it can be kept safe.
         */
        post: operations["reveal_recovery_key_api_v2_math_tutor_desktop_privacy_encryption_recovery_key_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/privacy/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Student Data
         * @description Whitelist-only export of the student's OWN, user-comprehensible
         *     data (document projections, memory projections, student summary).
         *     Secret/attestation/trace/reasoning/payload/path/hash fields CANNOT
         *     appear — the export fails closed if any unexpected field shows up.
         */
        get: operations["export_student_data_api_v2_math_tutor_desktop_privacy_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/privacy/purge-documents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Purge Documents
         * @description Delete ALL of the student's documents: live rows soft-deleted,
         *     chunk facts hard-deleted, derived vectors/index rows removed, every
         *     controlled storage file deleted. Never touches other students.
         */
        post: operations["purge_documents_api_v2_math_tutor_desktop_privacy_purge_documents_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/privacy/purge-memory": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Purge Memory
         * @description Soft-delete ALL live personal-memory nodes of the student
         *     (status-quo node semantics — no trash, immediately invisible).
         */
        post: operations["purge_memory_api_v2_math_tutor_desktop_privacy_purge_memory_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/privacy/rebuild-indexes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Rebuild Indexes
         * @description Rebuild the DERIVED embedding indexes from the chunk FACTS
         *     (invariant E — never re-imports user files). Without a provisioned
         *     embedding backend every document is honestly marked ``unavailable``.
         */
        post: operations["rebuild_indexes_api_v2_math_tutor_desktop_privacy_rebuild_indexes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/privacy/recompute-profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Recompute */
        post: operations["recompute_api_v2_math_tutor_desktop_privacy_recompute_profile_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/readiness": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Readiness */
        get: operations["readiness_api_v2_math_tutor_desktop_readiness_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/recommendations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Recommendations */
        get: operations["recommendations_api_v2_math_tutor_desktop_recommendations_get"];
        put?: never;
        post?: never;
        /** Delete */
        delete: operations["delete_api_v2_math_tutor_desktop_recommendations_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/recommendations/configuration": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Configure */
        put: operations["configure_api_v2_math_tutor_desktop_recommendations_configuration_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/recommendations/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start */
        post: operations["start_api_v2_math_tutor_desktop_recommendations_start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Settings
         * @description Current non-sensitive configuration (never a key value).
         */
        get: operations["get_settings_api_v2_math_tutor_desktop_settings_get"];
        /**
         * Put Settings
         * @description Apply a provider preset; the API key goes ONLY into the SecretStore.
         */
        put: operations["put_settings_api_v2_math_tutor_desktop_settings_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/api-key": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Delete Api Key
         * @description Remove the OS-stored credential and immediately fall back to templates.
         */
        delete: operations["delete_api_key_api_v2_math_tutor_desktop_settings_api_key_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/cost": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Cost Settings
         * @description Prices, budget and today's usage. Costs exist only where prices are set.
         */
        get: operations["get_cost_settings_api_v2_math_tutor_desktop_settings_cost_get"];
        /** Put Cost Settings */
        put: operations["put_cost_settings_api_v2_math_tutor_desktop_settings_cost_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/embedding": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Embedding Settings */
        get: operations["get_embedding_settings_api_v2_math_tutor_desktop_settings_embedding_get"];
        /** Put Embedding Settings */
        put: operations["put_embedding_settings_api_v2_math_tutor_desktop_settings_embedding_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/embedding/api-key": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Embedding Api Key */
        delete: operations["delete_embedding_api_key_api_v2_math_tutor_desktop_settings_embedding_api_key_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/embedding/local/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Download Local Embedding Model */
        post: operations["download_local_embedding_model_api_v2_math_tutor_desktop_settings_embedding_local_download_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/embedding/local/{model_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Local Embedding Model */
        delete: operations["delete_local_embedding_model_api_v2_math_tutor_desktop_settings_embedding_local__model_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/embedding/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Test Embedding Connection */
        post: operations["test_embedding_connection_api_v2_math_tutor_desktop_settings_embedding_test_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/learner": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Learner Settings
         * @description The learner's stage and grade; the question bank defaults to this stage.
         */
        get: operations["get_learner_settings_api_v2_math_tutor_desktop_settings_learner_get"];
        /** Put Learner Settings */
        put: operations["put_learner_settings_api_v2_math_tutor_desktop_settings_learner_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/models": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Models
         * @description System-side model discovery (sorted model ids).
         */
        get: operations["list_models_api_v2_math_tutor_desktop_settings_models_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/onboarding/skip": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Skip Provider Onboarding
         * @description Remember the explicit choice to continue in template teaching mode.
         */
        post: operations["skip_provider_onboarding_api_v2_math_tutor_desktop_settings_onboarding_skip_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/presets": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Presets
         * @description User-selectable provider presets (label + custom flag only).
         */
        get: operations["list_presets_api_v2_math_tutor_desktop_settings_presets_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/test-connection": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Test Connection
         * @description Legacy probe route with the same revision ownership as /model/test.
         */
        post: operations["test_connection_api_v2_math_tutor_desktop_settings_test_connection_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/settings/tutor": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Tutor Settings */
        get: operations["get_tutor_settings_api_v2_math_tutor_desktop_settings_tutor_get"];
        /** Put Tutor Settings */
        put: operations["put_tutor_settings_api_v2_math_tutor_desktop_settings_tutor_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/student-evidence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Evidence */
        get: operations["evidence_api_v2_math_tutor_desktop_student_evidence_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/student-evidence/{event_id}/exclude": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Exclude */
        post: operations["exclude_api_v2_math_tutor_desktop_student_evidence__event_id__exclude_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/desktop/student-summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Student Summary
         * @description Read-only evidence observations; probabilities remain internal.
         */
        get: operations["student_summary_api_v2_math_tutor_desktop_student_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/offers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Offers
         * @description Phase 5 contract: this student's practice offers — NO solution data.
         *
         *     The projection is strictly public: offer id/status, curriculum labels,
         *     difficulty, timestamps and the parent cycle. Never a solution, answer
         *     key, verification log, attestation or mastery value. ``EXPIRED`` is
         *     projected lazily (the stored status stays ACTIVE until consumed).
         */
        get: operations["list_offers_api_v2_math_tutor_offers_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/offers/{offer_id}/feedback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Offer Feedback */
        post: operations["offer_feedback_api_v2_math_tutor_offers__offer_id__feedback_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/offers/{offer_id}/resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resume Offer */
        post: operations["resume_offer_api_v2_math_tutor_offers__offer_id__resume_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Sessions */
        get: operations["list_sessions_api_v2_math_tutor_sessions_get"];
        put?: never;
        /** Create Session */
        post: operations["create_session_api_v2_math_tutor_sessions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/sessions/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Session */
        get: operations["get_session_api_v2_math_tutor_sessions__session_id__get"];
        put?: never;
        post?: never;
        /** Trash Session */
        delete: operations["trash_session_api_v2_math_tutor_sessions__session_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/trash": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Trash */
        get: operations["list_trash_api_v2_math_tutor_trash_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/trash/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Purge Session */
        delete: operations["purge_session_api_v2_math_tutor_trash__session_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/math-tutor/trash/{session_id}/restore": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Restore Session */
        post: operations["restore_session_api_v2_math_tutor_trash__session_id__restore_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** Attribution */
        Attribution: {
            /**
             * Language
             * @enum {string}
             */
            language: "en" | "zh";
            /**
             * License
             * @default CC BY-SA 4.0
             * @constant
             */
            license?: "CC BY-SA 4.0";
            /** Version */
            version: string;
        };
        BackupActionResult: components["schemas"]["BackupActionResultVariant1"] | components["schemas"]["BackupActionResultVariant2"];
        /** BackupActionResultVariant1 */
        BackupActionResultVariant1: {
            backup: components["schemas"]["BackupRecord"];
            /**
             * Ok
             * @constant
             */
            ok: true;
        };
        /** BackupActionResultVariant2 */
        BackupActionResultVariant2: {
            /** Message */
            message: string;
            /**
             * Ok
             * @constant
             */
            ok: false;
        };
        BackupIntegrity: "ok" | "unknown";
        /**
         * BackupPathRequest
         * @description Client-supplied backup name (a bare file NAME — never a path).
         */
        BackupPathRequest: {
            /** Path */
            path: string;
            /** Recovery Key */
            recovery_key?: string | null;
        };
        /** BackupRecord */
        BackupRecord: {
            /** Created At */
            created_at: string;
            /** Integrity */
            integrity: "ok" | "unknown";
            /** Path */
            path: string;
            /** Sha256 Prefix */
            sha256_prefix: string;
            /** Size Bytes */
            size_bytes: number;
        };
        BackupRestoreResult: components["schemas"]["BackupRestoreResultVariant1"] | components["schemas"]["BackupRestoreResultVariant2"];
        /** BackupRestoreResultVariant1 */
        BackupRestoreResultVariant1: {
            /** Message */
            message: string;
            /**
             * Ok
             * @constant
             */
            ok: true;
            /**
             * Restart Required
             * @constant
             */
            restart_required: true;
        };
        /** BackupRestoreResultVariant2 */
        BackupRestoreResultVariant2: {
            /** Message */
            message: string;
            /**
             * Ok
             * @constant
             */
            ok: false;
            /** Recovery Required */
            recovery_required?: boolean;
        };
        BackupVerifyResult: components["schemas"]["BackupVerifyResultVariant1"] | components["schemas"]["BackupVerifyResultVariant2"];
        /** BackupVerifyResultVariant1 */
        BackupVerifyResultVariant1: {
            /**
             * Ok
             * @constant
             */
            ok: true;
        };
        /** BackupVerifyResultVariant2 */
        BackupVerifyResultVariant2: {
            /** Message */
            message: string;
            /**
             * Ok
             * @constant
             */
            ok: false;
        };
        /** BackupsList */
        BackupsList: {
            /** Backup Dir */
            backup_dir: string;
            /** Backups */
            backups: components["schemas"]["BackupRecord"][];
            policy: components["schemas"]["BackupsListPolicy"];
        };
        /** BackupsListPolicy */
        BackupsListPolicy: {
            /** Mode */
            mode: string;
            /** Retention Limit */
            retention_limit: number;
        };
        /** BinaryEvidenceCounts */
        BinaryEvidenceCounts: {
            /** Correct */
            correct: number;
            /** Incorrect */
            incorrect: number;
        };
        /** Body_import_document_api_v2_math_tutor_desktop_documents_import_post */
        Body_import_document_api_v2_math_tutor_desktop_documents_import_post: {
            /** File */
            file: string;
        };
        /** BootstrapPayload */
        BootstrapPayload: {
            /** Phase */
            phase: string;
            /** Readiness */
            readiness: "READY" | "DEGRADED" | "BLOCKED";
            /** Reason */
            reason: string | null;
            /** Steps */
            steps: components["schemas"]["BootstrapStep"][];
        };
        /** BootstrapStep */
        BootstrapStep: {
            /** Detail */
            detail: string | null;
            /** Key */
            key: string;
            /** Label */
            label: string;
            /** Status */
            status: "ok" | "degraded" | "blocked";
        };
        BootstrapStepStatus: "ok" | "degraded" | "blocked";
        /** CheckChoice */
        CheckChoice: {
            /** Id */
            id: string;
            /** Text */
            text: string;
        };
        /** CheckPrompt */
        CheckPrompt: {
            /** Check Id */
            check_id: string;
            /**
             * Choices
             * @default []
             */
            choices?: components["schemas"]["CheckChoice"][];
            /** Concept Id */
            concept_id: string;
            /** Prompt */
            prompt: string;
            /**
             * Purpose
             * @enum {string}
             */
            purpose: "boundary" | "transfer";
            /**
             * Response Type
             * @enum {string}
             */
            response_type: "choice" | "number";
        };
        CheckValue: "ok" | "degraded" | "error";
        /** ConfigOperation */
        ConfigOperation: {
            /** Epoch */
            epoch?: string | null;
            /** Operation Id */
            operation_id?: string | null;
            /** Revision */
            revision?: number | null;
        };
        /** ConfigurationOperation */
        ConfigurationOperation: {
            /** Epoch */
            epoch?: string;
            /** Operation Id */
            operation_id?: string;
            /** Revision */
            revision?: number;
        };
        /** ConfigurationReceipt */
        ConfigurationReceipt: {
            /** Accepted */
            accepted?: boolean;
            /** Current Revision */
            current_revision?: number;
            /** Epoch */
            epoch?: string;
            /** Operation Id */
            operation_id?: string;
            /** Persisted */
            persisted?: boolean;
            /** Persistence Error */
            persistence_error?: "config_write_failed" | "persistence_unavailable" | null;
            /** Provider Id */
            provider_id?: string;
            /** Revision */
            revision?: number;
        };
        /** ConversationCreate */
        ConversationCreate: {
            /** Conversation Id */
            conversation_id: string;
        };
        /** CostSettings */
        CostSettings: {
            /** Currency */
            currency: string;
            /** Daily Budget */
            daily_budget: number | null;
            /** Daily Token Budget */
            daily_token_budget: number | null;
            /** Input Price Per Mtok */
            input_price_per_mtok: number | null;
            /** Output Price Per Mtok */
            output_price_per_mtok: number | null;
            /** Over Budget */
            over_budget: boolean;
            today: components["schemas"]["CostSettingsToday"];
        };
        /** CostSettingsInput */
        CostSettingsInput: {
            /** Currency */
            currency: string;
            /** Daily Budget */
            daily_budget: number | null;
            /** Daily Token Budget */
            daily_token_budget: number | null;
            /** Input Price Per Mtok */
            input_price_per_mtok: number | null;
            /** Output Price Per Mtok */
            output_price_per_mtok: number | null;
        };
        /** CostSettingsToday */
        CostSettingsToday: {
            /** Cost */
            cost: number;
            /** Currency */
            currency: string;
            /** Date */
            date: string;
            /** Tokens */
            tokens: number;
        };
        /** CostSettingsUpdate */
        CostSettingsUpdate: {
            /**
             * Currency
             * @default CNY
             */
            currency?: string;
            /** Daily Budget */
            daily_budget?: number | null;
            /** Daily Token Budget */
            daily_token_budget?: number | null;
            /** Input Price Per Mtok */
            input_price_per_mtok?: number | null;
            /** Output Price Per Mtok */
            output_price_per_mtok?: number | null;
        };
        /** DesktopDocument */
        DesktopDocument: {
            /** Chunk Count */
            chunk_count: number;
            /** Conversation Ids */
            conversation_ids?: string[];
            /** Conversation Titles */
            conversation_titles?: {
                [key: string]: string;
            };
            /** Created At */
            created_at: string;
            /** Document Id */
            document_id: string;
            /** Empty Page Count */
            empty_page_count: number;
            /** Error */
            error: string | null;
            /** Filename */
            filename: string;
            /** Image Count */
            image_count: number;
            /** Is Global */
            is_global?: boolean;
            /** Mime Type */
            mime_type: string;
            /** Page Count */
            page_count: number;
            /** Parse Warning */
            parse_warning: string | null;
            /** Retrieval Enabled */
            retrieval_enabled: boolean;
            /** Size Bytes */
            size_bytes: number;
            /** Status */
            status: "importing" | "parsing" | "ready" | "ready_with_warnings" | "needs_ocr" | "failed";
        };
        /** DesktopMemory */
        DesktopMemory: {
            /** Confidence */
            confidence: number;
            /** Created At */
            created_at: string;
            /** Memory Id */
            memory_id: string;
            /** Memory Type */
            memory_type: string;
            /** Object Json */
            object_json: {
                [key: string]: unknown;
            };
            /** Predicate */
            predicate: string;
            /** Retrieval Enabled */
            retrieval_enabled: boolean;
            /** Source Type */
            source_type: "USER_EXPLICIT" | "MODEL_INFERRED" | "USER_CONFIRMED";
            /** Subject */
            subject: string;
            /** Updated At */
            updated_at: string;
        };
        /** DesktopSettings */
        DesktopSettings: {
            /** Accepted */
            accepted?: boolean;
            /** Base Url */
            base_url: string;
            /** Connection Status */
            connection_status?: "unconfigured" | "configured" | "connecting" | "success" | "failure";
            /** Current Revision */
            current_revision?: number;
            /** Epoch */
            epoch?: string;
            /** Initial Assessment Required */
            initial_assessment_required?: boolean;
            /** Is Configured */
            is_configured: boolean;
            /** Key Masked */
            key_masked: string | null;
            /** Model */
            model: string;
            /** Onboarding Completed */
            onboarding_completed: boolean;
            /** Operation Id */
            operation_id?: string;
            /** Persisted */
            persisted?: boolean;
            /** Persistence Error */
            persistence_error?: "config_write_failed" | "persistence_unavailable" | null;
            /** Preset Id */
            preset_id: string;
            /** Provider Configs */
            provider_configs?: {
                [key: string]: components["schemas"]["DesktopSettingsProvider_configsValue"];
            };
            /** Provider Id */
            provider_id?: string;
            /** Revision */
            revision?: number;
            /** Vision Mode */
            vision_mode?: "auto" | "enabled" | "disabled";
        };
        /** DesktopSettingsProvider_configsValue */
        DesktopSettingsProvider_configsValue: {
            /** Base Url */
            base_url: string;
            /** Has Api Key */
            has_api_key: boolean;
            /** Key Masked */
            key_masked: string | null;
            /** Model */
            model: string;
            /** Vision Mode */
            vision_mode?: "auto" | "enabled" | "disabled";
        };
        /** DiscoveredResources */
        DiscoveredResources: {
            /** Query */
            query: string;
            /** Resources */
            resources: components["schemas"]["RecommendationResource"][];
            /** Retrieved At */
            retrieved_at: string;
            /**
             * Status
             * @enum {string}
             */
            status: "ready" | "empty";
        };
        /** DocumentRename */
        DocumentRename: {
            /** Filename */
            filename: string;
        };
        /** DocumentScopeInput */
        DocumentScopeInput: {
            /** Is Global */
            is_global: boolean;
        };
        DocumentStatus: "importing" | "parsing" | "ready" | "ready_with_warnings" | "needs_ocr" | "failed";
        /** EducationalHistoryResult */
        EducationalHistoryResult: {
            /** By Table */
            by_table: {
                [key: string]: number;
            };
            /** Deleted Rows */
            deleted_rows: number;
            /** Kept Skeleton Tables */
            kept_skeleton_tables: string[];
            /** Ok */
            ok: boolean;
            projection: components["schemas"]["EducationalHistoryResultProjectionVariant1"] | null;
            /** Teaching Contexts Cleared */
            teaching_contexts_cleared: number;
        };
        /** EducationalHistoryResultProjectionVariant1 */
        EducationalHistoryResultProjectionVariant1: {
            /** Estimator Version */
            estimator_version: string;
            /** Evidence Remaining */
            evidence_remaining: number;
            /** Observations Remaining */
            observations_remaining: number;
            /** Projection Version */
            projection_version: number;
        };
        EmbeddingProvider: "local" | "cloud";
        /** EmbeddingSettings */
        EmbeddingSettings: {
            /** Cloud Base Url */
            cloud_base_url: string;
            /** Cloud Has Api Key */
            cloud_has_api_key: boolean;
            /** Cloud Key Masked */
            cloud_key_masked: string | null;
            /** Cloud Model */
            cloud_model: string;
            /** Enabled */
            enabled: boolean;
            /** Local Download Error */
            local_download_error: string | null;
            /** Local Download Status */
            local_download_status: "not_downloaded" | "downloading" | "ready" | "failed";
            /** Local Model Id */
            local_model_id: string;
            /** Local Models */
            local_models: components["schemas"]["LocalEmbeddingModel"][];
            /** Provider */
            provider: "local" | "cloud";
            /** Reindex Required */
            reindex_required: boolean;
            /** Runtime Reason */
            runtime_reason: string | null;
            /** Status */
            status: "disabled" | "local_ready" | "cloud_configured" | "incomplete";
            /** Status Label */
            status_label: string;
        };
        /** EmbeddingSettingsUpdate */
        EmbeddingSettingsUpdate: {
            /** Cloud Api Key */
            cloud_api_key?: string | null;
            /**
             * Cloud Base Url
             * @default
             */
            cloud_base_url?: string;
            /**
             * Cloud Model
             * @default
             */
            cloud_model?: string;
            /**
             * Enabled
             * @default false
             */
            enabled?: boolean;
            /**
             * Local Model Id
             * @default bge-small-zh-v1.5
             */
            local_model_id?: string;
            /**
             * Provider
             * @default local
             */
            provider?: string;
        };
        EmbeddingStatus: "disabled" | "local_ready" | "cloud_configured" | "incomplete";
        /** EmbeddingTestResult */
        EmbeddingTestResult: {
            /** Message */
            message: string;
            /** Ok */
            ok: boolean;
        };
        /** EncryptionUpdate */
        EncryptionUpdate: {
            /** Enabled */
            enabled: boolean;
        };
        /** EvidenceCard */
        EvidenceCard: {
            attribution?: components["schemas"]["Attribution"] | null;
            /** Author */
            author: string | null;
            /** Context */
            context: string;
            /**
             * Mathematical Status
             * @default not_evaluated
             * @constant
             */
            mathematical_status?: "not_evaluated";
            /** Original Url */
            original_url: string;
            /**
             * Provider
             * @default zhihu
             */
            provider?: "zhihu" | ("wikipedia" | "wikibooks" | "active_calculus" | "open_math_books");
            /** Quote */
            quote: string;
            /**
             * Quote Integrity
             * @default exact_snapshot_text
             * @constant
             */
            quote_integrity?: "exact_snapshot_text";
            /** Reading Question */
            reading_question?: string | null;
            /**
             * Semantic Support
             * @default not_evaluated
             * @constant
             */
            semantic_support?: "not_evaluated";
            /** Source Id */
            source_id: string;
            /**
             * Source Scope
             * @default search_excerpt
             * @enum {string}
             */
            source_scope?: "search_excerpt" | "page_excerpt" | "textbook_excerpt";
            /** Span Id */
            span_id: string;
            /** Title */
            title: string;
        };
        /** EvidenceGap */
        EvidenceGap: {
            /** Code */
            code: string;
            /**
             * Source Ids
             * @default []
             */
            source_ids?: string[];
        };
        /** EvidencePage */
        EvidencePage: {
            /** Items */
            items: components["schemas"]["LearningEvidence"][];
            /** Next Cursor */
            next_cursor: number | null;
        };
        /** EvidencePlan */
        EvidencePlan: {
            /** Cards */
            cards: components["schemas"]["EvidenceCard"][];
            /** Comparisons */
            comparisons: components["schemas"]["UnverifiedComparison"][];
            /** Distinct Excerpt Count */
            distinct_excerpt_count: number;
            /** Gaps */
            gaps: components["schemas"]["EvidenceGap"][];
            /** Interpretations */
            interpretations: components["schemas"]["UnverifiedInterpretation"][];
            /** Question */
            question: string;
            /** Rejected Candidate Items */
            rejected_candidate_items: string[];
            /** Source Rejections */
            source_rejections: components["schemas"]["SourceRejection"][];
            /** Sources */
            sources: components["schemas"]["SourceSnapshot"][];
            /** Spans */
            spans: components["schemas"]["EvidenceSpan"][];
            /**
             * Status
             * @enum {string}
             */
            status: "evidence_available" | "no_evidence";
            /** Unselected Source Ids */
            unselected_source_ids: string[];
        };
        /** EvidenceSpan */
        EvidenceSpan: {
            /** Context */
            context: string;
            /** Context End */
            context_end: number;
            /** Context Start */
            context_start: number;
            /** End */
            end: number;
            /**
             * Offset Unit
             * @default unicode_codepoint
             * @constant
             */
            offset_unit?: "unicode_codepoint";
            /** Source Id */
            source_id: string;
            /** Span Id */
            span_id: string;
            /** Start */
            start: number;
            /** Text */
            text: string;
        };
        /** EvidenceSummary */
        EvidenceSummary: {
            /** Assisted */
            assisted: number;
            /** Diagnostic */
            diagnostic: number;
            /** Independent */
            independent: number;
            /** Post Solution */
            post_solution: number;
            /** Status */
            status?: string;
            /** Ungradable */
            ungradable: number;
        };
        /** ExplorationConfiguration */
        ExplorationConfiguration: {
            /** Configured */
            configured: boolean;
            /** Environment Managed */
            environment_managed: boolean;
            /** Has Saved Secret */
            has_saved_secret: boolean;
            /** Persistent */
            persistent: boolean;
        };
        /** ExplorationCredential */
        ExplorationCredential: {
            /**
             * Api Key
             * Format: password
             */
            api_key: string;
        };
        /** ExplorationView */
        ExplorationView: {
            /**
             * Ai Status
             * @enum {string}
             */
            ai_status: "not_requested" | "ready" | "unavailable";
            evidence: components["schemas"]["EvidencePlan"];
            /**
             * Goal
             * @enum {string}
             */
            goal: "understand" | "apply" | "compare";
            /** Inquiry Id */
            inquiry_id: string;
            last_check: components["schemas"]["CheckPrompt"] | null;
            /** Last Correctness */
            last_correctness: ("correct" | "incorrect" | "unknown" | "explanation") | null;
            /** Last Feedback */
            last_feedback: string;
            learning: components["schemas"]["LearningPlan"];
            /**
             * Mode
             * @default zhihu
             * @enum {string}
             */
            mode?: "open" | "zhihu";
            /** Observation Count */
            observation_count: number;
            /** Organization Attempts */
            organization_attempts: number;
            /** Question */
            question: string;
            /** Reflection */
            reflection: string;
            /** Retrieval Attempts */
            retrieval_attempts?: components["schemas"]["RetrievalAttempt"][];
            /** Revision */
            revision: number;
            /** Updated At */
            updated_at: string;
        };
        /** ExportEvidenceCounts */
        ExportEvidenceCounts: {
            assisted: components["schemas"]["BinaryEvidenceCounts"];
            diagnostic: components["schemas"]["BinaryEvidenceCounts"];
            /** Duplicate Responses */
            duplicate_responses: number;
            independent: components["schemas"]["BinaryEvidenceCounts"];
            /** Joint Task Evidence */
            joint_task_evidence: number;
            post_solution: components["schemas"]["BinaryEvidenceCounts"];
            /** Repeat Attempts */
            repeat_attempts?: number;
            /** Step Correct */
            step_correct: number;
            /** Ungradable */
            ungradable: number;
        };
        /** ExportLearningLoop */
        ExportLearningLoop: {
            /** Diagnostic Status */
            diagnostic_status: string;
            /** Domain */
            domain: string;
            /** Due At */
            due_at: string | null;
            /** Evidence */
            evidence: {
                [key: string]: number;
            };
            /** Phase */
            phase: string;
            /** Review Round */
            review_round: number;
        };
        /** ExportMisconception */
        ExportMisconception: {
            /** Confidence */
            confidence: number | null;
            /** Label */
            label?: string;
            /** Last Seen At */
            last_seen_at?: string | null;
            /** Rule Id */
            rule_id: string;
            /** Skill Ids */
            skill_ids?: string[];
            /** Status */
            status: string;
        };
        /** ExportSkill */
        ExportSkill: {
            /** Evidence Status */
            evidence_status: string;
            evidence_summary: components["schemas"]["ExportEvidenceCounts"];
            /** Skill Id */
            skill_id: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** InitialAnswer */
        InitialAnswer: {
            /** Index */
            index: number;
            /**
             * Option Id
             * @enum {string}
             */
            option_id: "A" | "B" | "C" | "D" | "unsure";
            /** Run Id */
            run_id: string;
            /** Version */
            version: string;
        };
        /** InitialResume */
        InitialResume: {
            /** Run Id */
            run_id: string;
            /** Version */
            version: string;
        };
        /** InitialRun */
        InitialRun: {
            /** Run Id */
            run_id: string;
        };
        /** InquiryCreate */
        InquiryCreate: {
            /** Generation */
            generation: number;
            /**
             * Goal
             * @default understand
             * @enum {string}
             */
            goal?: "understand" | "apply" | "compare";
            /**
             * Inquiry Id
             * Format: uuid
             */
            inquiry_id: string;
            /**
             * Language
             * @default zh
             * @enum {string}
             */
            language?: "zh" | "en";
            /**
             * Mode
             * @description New inquiries default to open. Replays retain the saved source.
             */
            mode?: ("open" | "zhihu") | null;
            /** Question */
            question: string;
        };
        /** InquiryExplanation */
        InquiryExplanation: {
            /** Check Id */
            check_id: string;
            /**
             * Language
             * @default zh
             * @enum {string}
             */
            language?: "zh" | "en";
            /** Revision */
            revision: number;
        };
        /** InquiryList */
        InquiryList: {
            /** Generation */
            generation: number;
            /** Items */
            items: components["schemas"]["InquirySummary"][];
        };
        /** InquiryOperation */
        InquiryOperation: {
            /**
             * Language
             * @default zh
             * @enum {string}
             */
            language?: "zh" | "en";
            /** Revision */
            revision: number;
        };
        /** InquiryReflection */
        InquiryReflection: {
            /**
             * Language
             * @default zh
             * @enum {string}
             */
            language?: "zh" | "en";
            /** Reflection */
            reflection: string;
            /** Revision */
            revision: number;
        };
        /** InquiryResponse */
        InquiryResponse: {
            /** Answer */
            answer: string;
            /** Check Id */
            check_id: string;
            /**
             * Language
             * @default zh
             * @enum {string}
             */
            language?: "zh" | "en";
            /** Revision */
            revision: number;
        };
        /** InquirySummary */
        InquirySummary: {
            /**
             * Goal
             * @enum {string}
             */
            goal: "understand" | "apply" | "compare";
            /** Inquiry Id */
            inquiry_id: string;
            /** Question */
            question: string;
            /** Revision */
            revision: number;
            /** Updated At */
            updated_at: string;
        };
        /** ItemErrorObservation */
        ItemErrorObservation: {
            /** Assessment Id */
            assessment_id: string;
            /** Correction Event Id */
            correction_event_id: string | null;
            /** Cycle Id */
            cycle_id: string;
            /** Event Id */
            event_id: string;
            /** Label */
            label: string;
            /** Last Seen At */
            last_seen_at: string | null;
            /** Related Skill Ids */
            related_skill_ids: string[];
            /** Rule Id */
            rule_id: string;
            /** Status */
            status: "unlocalized" | "corrected_later";
        };
        /** LearnerUpdate */
        LearnerUpdate: {
            /** Grade */
            grade?: number | null;
            /** Stage */
            stage?: string | null;
        };
        /** LearningActionPlan */
        LearningActionPlan: {
            /**
             * Action
             * @enum {string}
             */
            action: "explain" | "check" | "continue" | "review_prerequisite" | "explore";
            /** Assessment Scope */
            assessment_scope: string;
            /** Catalog Version */
            catalog_version: string;
            /** Evidence Count */
            evidence_count: number;
            /** Evidence Ids */
            evidence_ids: string[];
            /** Goal */
            goal: string;
            /** Goal Label */
            goal_label: string;
            /** Graph Version */
            graph_version: string;
            /** Last Event Seq */
            last_event_seq: number;
            /** Policy */
            policy: string;
            /** Prerequisites */
            prerequisites: components["schemas"]["RecommendationPrerequisite"][];
            /** Profile Revision */
            profile_revision: string;
            /** Query */
            query: string;
            /** Reason */
            reason: string;
            /** Reason Code */
            reason_code: string;
            /** Resources */
            resources: components["schemas"]["RecommendationResource"][];
            /** Target */
            target: string;
            /** Target Label */
            target_label: string;
            /** Title */
            title: string;
        };
        /** LearningEvidence */
        LearningEvidence: {
            /** Completion Scope */
            completion_scope: string;
            /** Correctness */
            correctness: string | null;
            /** Cycle Id */
            cycle_id: string;
            /** Event Id */
            event_id: string;
            /** Event Seq */
            event_seq: number;
            /** Evidence Kind */
            evidence_kind: string;
            /** Excluded */
            excluded: boolean;
            /** First Target */
            first_target: boolean;
            /** Occurred At */
            occurred_at: string;
            /** Problem Text */
            problem_text: string;
            /** Session Id */
            session_id: string | null;
            /** Skill Ids */
            skill_ids: string[];
            /** Student Response */
            student_response: string;
        };
        /** LearningLoopAction */
        LearningLoopAction: {
            /**
             * Domain
             * @enum {string}
             */
            domain: "fraction_addition" | "signed_subtraction" | "linear_equation";
            /** Episode Id */
            episode_id: string;
            /** Probe Id */
            probe_id: string;
            /** Request Id */
            request_id: string;
        };
        /** LearningLoopAnswer */
        LearningLoopAnswer: {
            /** Answer */
            answer: string;
            /**
             * Domain
             * @enum {string}
             */
            domain: "fraction_addition" | "signed_subtraction" | "linear_equation";
            /** Episode Id */
            episode_id: string;
            /** Probe Id */
            probe_id: string;
            /** Request Id */
            request_id: string;
        };
        /** LearningLoopStart */
        LearningLoopStart: {
            /**
             * Domain
             * @enum {string}
             */
            domain: "fraction_addition" | "signed_subtraction" | "linear_equation";
        };
        /** LearningPlan */
        LearningPlan: {
            /** Basis Observation Ids */
            basis_observation_ids: string[];
            check: components["schemas"]["CheckPrompt"] | null;
            /** Concept Title */
            concept_title: string;
            /**
             * Evidence State
             * @enum {string}
             */
            evidence_state: "unknown" | "assisted_only" | "needs_check" | "mixed_observations" | "independent_observed";
            /**
             * Goal
             * @enum {string}
             */
            goal: "understand" | "apply" | "compare";
            /** Independent Successes */
            independent_successes: number;
            /** Original Question */
            original_question: string;
            /**
             * Policy
             * @default exploration_learning_v1
             */
            policy?: string;
            /**
             * Prerequisite Basis
             * @enum {string}
             */
            prerequisite_basis: "authored_curriculum" | "provided_curriculum" | "none";
            /** Steps */
            steps: components["schemas"]["LearningStep"][];
            /** Target Concept */
            target_concept: string;
        };
        /** LearningStep */
        LearningStep: {
            /**
             * Action
             * @enum {string}
             */
            action: "read" | "worked_example" | "compare_methods" | "independent_check" | "clarify_conflict" | "transfer_check" | "review_prerequisite" | "choose_goal";
            /**
             * Basis Observation Ids
             * @default []
             */
            basis_observation_ids?: string[];
            /** Concept Id */
            concept_id: string;
            /** Reason */
            reason: string;
            /** Step Id */
            step_id: string;
            /** Title */
            title: string;
        };
        /** LibraryExcerpt */
        LibraryExcerpt: {
            /**
             * Chunk Id
             * Format: uuid
             */
            chunk_id: string;
            /**
             * Document Id
             * Format: uuid
             */
            document_id: string;
            /** Filename */
            filename: string;
            /** Page */
            page: number | null;
            /** Page End */
            page_end: number | null;
            /** Section */
            section: string;
            /** Text */
            text: string;
            /** Truncated */
            truncated: boolean;
        };
        /** LibraryQuery */
        LibraryQuery: {
            /** Question */
            question: string;
        };
        /** LocalEmbeddingDownloadRequest */
        LocalEmbeddingDownloadRequest: {
            /**
             * Model Id
             * @default bge-small-zh-v1.5
             */
            model_id?: string;
        };
        LocalEmbeddingDownloadStatus: "not_downloaded" | "downloading" | "ready" | "failed";
        /** LocalEmbeddingModel */
        LocalEmbeddingModel: {
            /** Dimension */
            dimension: number;
            /** Label */
            label: string;
            /** Model Id */
            model_id: string;
            /** Size Label */
            size_label: string;
            /** Source */
            source: string;
        };
        /** MemoryConfirmation */
        MemoryConfirmation: {
            /** Expected Updated At */
            expected_updated_at?: string | null;
        };
        /** MemoryCreate */
        MemoryCreate: {
            /** Confidence */
            confidence?: number | null;
            /** Memory Type */
            memory_type: string;
            /** Object Json */
            object_json?: {
                [key: string]: unknown;
            };
            /** Predicate */
            predicate: string;
            /** Subject */
            subject: string;
        };
        MemorySourceType: "USER_EXPLICIT" | "MODEL_INFERRED" | "USER_CONFIRMED";
        /** MemoryUpdate */
        MemoryUpdate: {
            /** Confidence */
            confidence?: number | null;
            /** Expected Updated At */
            expected_updated_at?: string | null;
            /** Object Json */
            object_json?: {
                [key: string]: unknown;
            } | null;
            /** Predicate */
            predicate?: string | null;
        };
        ModelErrorKind: "response_incomplete" | "request_rejected" | "quota_exceeded" | "rate_limited" | "provider_error" | "credential_invalid" | "network_unavailable" | "provider_unsupported" | "model_unavailable" | "gateway_disabled";
        /** ModelTestResult */
        ModelTestResult: {
            /** Accepted */
            accepted?: boolean;
            /** Current Revision */
            current_revision?: number;
            /** Epoch */
            epoch?: string;
            /** Error Kind */
            error_kind: "response_incomplete" | "request_rejected" | "quota_exceeded" | "rate_limited" | "provider_error" | "credential_invalid" | "network_unavailable" | "provider_unsupported" | "model_unavailable" | "gateway_disabled" | null;
            /** Message */
            message: string | null;
            /** Ok */
            ok: boolean;
            /** Operation Id */
            operation_id?: string;
            /** Persisted */
            persisted?: boolean;
            /** Persistence Error */
            persistence_error?: "config_write_failed" | "persistence_unavailable" | null;
            /** Provider Id */
            provider_id?: string;
            /** Resolved Model */
            resolved_model?: string;
            /** Revision */
            revision?: number;
        };
        /** OfferFeedbackInput */
        OfferFeedbackInput: {
            /** Kind */
            kind: string;
        };
        OfferStatus: "ACTIVE" | "ACCEPTED" | "EXPIRED" | "REVOKED";
        /** PracticeOffer */
        PracticeOffer: {
            /** Basis */
            basis?: {
                [key: string]: unknown;
            } | null;
            /** Child Cycle Id */
            child_cycle_id?: string | null;
            /** Concept Labels */
            concept_labels: string[];
            /** Difficulty */
            difficulty: number | null;
            /** Display Status */
            display_status?: "pending" | "in_progress" | "completed" | "later" | "history";
            /** Evidence Href */
            evidence_href?: string;
            /** Evidence Ids */
            evidence_ids?: string[];
            /** Expires At */
            expires_at: string;
            /** Feedback */
            feedback?: "later" | "not_relevant" | null;
            /** History Cutoff Seq */
            history_cutoff_seq?: number | null;
            /** Observation Goal */
            observation_goal?: string;
            /** Observation Kind */
            observation_kind?: "independent_transfer" | "diagnostic";
            /** Offer Id */
            offer_id: string;
            /** Offered At */
            offered_at: string;
            /** Parent Cycle Id */
            parent_cycle_id: string;
            /** Purpose */
            purpose?: string;
            /** Question Count */
            question_count?: number;
            /** Reason */
            reason?: string;
            /** Response Mode */
            response_mode?: "free_response" | "single_choice";
            result_summary?: components["schemas"]["PracticeOfferResult_summaryVariant1"] | null;
            /** Resume Session Id */
            resume_session_id?: string | null;
            /** Skill Labels */
            skill_labels: string[];
            /** Status */
            status: "ACTIVE" | "ACCEPTED" | "EXPIRED" | "REVOKED";
            /** Title */
            title?: string;
            /** Update Reason */
            update_reason?: string | null;
        };
        /** PracticeOfferResult_summaryVariant1 */
        PracticeOfferResult_summaryVariant1: {
            /** Diagnostic Correct */
            diagnostic_correct?: number;
            /** First Free Response */
            first_free_response?: number;
            /** Helped */
            helped: number;
            /** Independent Correct */
            independent_correct: number;
            /** Observations */
            observations: number;
        };
        /** ProviderPreset */
        ProviderPreset: {
            /** Base Url */
            base_url?: string;
            /** Custom */
            custom: boolean;
            /** Default Model */
            default_model?: string;
            /** Editable Base Url */
            editable_base_url?: boolean;
            /** Label */
            label: string;
            /** Local */
            local?: boolean;
            /** Preset Id */
            preset_id: string;
            /** Requires Api Key */
            requires_api_key?: boolean;
        };
        /** PurgeDocumentsResult */
        PurgeDocumentsResult: {
            /** Chunks Removed */
            chunks_removed: number;
            /** Documents Soft Deleted */
            documents_soft_deleted: number;
            /** Index Builds Removed */
            index_builds_removed: number;
            /** Ok */
            ok: boolean;
            /** Storage Files Removed */
            storage_files_removed: number;
            /** Vectors Cleared */
            vectors_cleared: number;
        };
        /** PurgeMemoryResult */
        PurgeMemoryResult: {
            /** Memories Soft Deleted */
            memories_soft_deleted: number;
            /** Ok */
            ok: boolean;
        };
        /** Readiness */
        Readiness: {
            /** Checks */
            checks: {
                [key: string]: "ok" | "degraded" | "error";
            };
            /** Reasons */
            reasons: {
                [key: string]: string;
            };
            /** Status */
            status: "READY" | "DEGRADED" | "BLOCKED";
        };
        ReadinessStatus: "READY" | "DEGRADED" | "BLOCKED";
        /** RebuildIndexesResult */
        RebuildIndexesResult: {
            /** Documents */
            documents: {
                [key: string]: components["schemas"]["RebuildIndexesResultDocumentsValue"];
            };
            /** Ok */
            ok: boolean;
        };
        /** RebuildIndexesResultDocumentsValue */
        RebuildIndexesResultDocumentsValue: {
            /** Index Version */
            index_version: number | null;
            /** Reason */
            reason?: string;
            /** Status */
            status: "rebuilt" | "unavailable" | "no_chunks";
        };
        /** RecommendationGoal */
        RecommendationGoal: {
            /** Id */
            id: string;
            /** Label */
            label: string;
        };
        /** RecommendationPrerequisite */
        RecommendationPrerequisite: {
            /** Id */
            id: string;
            /** Observed */
            observed: boolean;
        };
        /** RecommendationResource */
        RecommendationResource: {
            /** Author */
            author?: string | null;
            /** Knowledge Points */
            knowledge_points?: string[];
            /** Prerequisites */
            prerequisites?: string[];
            /** Provenance */
            provenance: {
                [key: string]: unknown;
            };
            /** Published At */
            published_at?: string | null;
            /**
             * Recommendation Reason
             * @default
             */
            recommendation_reason?: string;
            /** Resource Id */
            resource_id: string;
            /** Review */
            review?: {
                [key: string]: unknown;
            };
            /** Review Status */
            review_status: string;
            /**
             * Selection Reason
             * @default
             */
            selection_reason?: string;
            /** Source Time */
            source_time?: string | null;
            /**
             * Source Time Kind
             * @default unknown
             */
            source_time_kind?: string;
            /** Summary */
            summary: string;
            /** Tags */
            tags?: string[];
            /** Title */
            title: string;
            /** Url */
            url: string;
        };
        /** RecommendationSettings */
        RecommendationSettings: {
            /** Enabled */
            enabled: boolean;
            /** Goal */
            goal: string;
            /**
             * Language
             * @default zh
             * @enum {string}
             */
            language?: "zh" | "en";
        };
        /** RecommendationView */
        RecommendationView: {
            discovery: components["schemas"]["DiscoveredResources"] | null;
            /** Enabled */
            enabled: boolean;
            /** Expires At */
            expires_at: string | null;
            /** Goal */
            goal: string;
            /** Goals */
            goals: components["schemas"]["RecommendationGoal"][];
            plan: components["schemas"]["LearningActionPlan"];
            /**
             * Status
             * @enum {string}
             */
            status: "disabled" | "idle" | "running" | "cached" | "rate_limited" | "not_configured" | "failed";
            /** Updated At */
            updated_at: string | null;
        };
        /** RetrievalAttempt */
        RetrievalAttempt: {
            /**
             * Access
             * @default online
             * @enum {string}
             */
            access?: "online" | "bundled";
            /**
             * Count
             * @default 0
             */
            count?: number;
            /**
             * Language
             * @enum {string}
             */
            language: "zh" | "en";
            /**
             * Provider
             * @enum {string}
             */
            provider: "wikipedia" | "wikibooks" | "active_calculus" | "open_math_books";
            /**
             * Status
             * @enum {string}
             */
            status: "found" | "empty" | "unavailable" | "rate_limited";
        };
        /** RetrievalToggle */
        RetrievalToggle: {
            /** Enabled */
            enabled: boolean;
            /** Expected Updated At */
            expected_updated_at?: string | null;
        };
        /** ReviewObservation */
        ReviewObservation: {
            /**
             * Category
             * @enum {string}
             */
            category: "calculation" | "conditions" | "method_transfer";
            /** Corrected Later */
            corrected_later: boolean;
            /** Cycle Id */
            cycle_id: string;
            /** Event Id */
            event_id: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "independent" | "assisted" | "post_solution" | "repeat" | "choice";
            /** Next Problem */
            next_problem: string | null;
            /** Occurred At */
            occurred_at: string;
            /** Reason */
            reason: string;
        };
        /** SettingsSaveResult */
        SettingsSaveResult: {
            /** Accepted */
            accepted?: boolean;
            /** Base Url */
            base_url: string;
            /** Connection Status */
            connection_status?: "unconfigured" | "configured" | "connecting" | "success" | "failure";
            /** Current Revision */
            current_revision?: number;
            /** Epoch */
            epoch?: string;
            /** Initial Assessment Required */
            initial_assessment_required?: boolean;
            /** Is Configured */
            is_configured: boolean;
            /** Key Masked */
            key_masked: string | null;
            /** Model */
            model: string;
            /** Onboarding Completed */
            onboarding_completed: boolean;
            /** Operation Id */
            operation_id?: string;
            /** Persisted */
            persisted?: boolean;
            /** Persistence Error */
            persistence_error?: "config_write_failed" | "persistence_unavailable" | null;
            /** Preset Id */
            preset_id: string;
            /** Provider Id */
            provider_id?: string;
            /** Revision */
            revision?: number;
            /** Vision Mode */
            vision_mode?: "auto" | "enabled" | "disabled";
        };
        /** SettingsUpdate */
        SettingsUpdate: {
            /** Api Key */
            api_key?: string | null;
            /**
             * Base Url
             * @default
             */
            base_url?: string;
            /** Expected Epoch */
            expected_epoch?: string | null;
            /** Expected Revision */
            expected_revision?: number | null;
            /**
             * Model
             * @default
             */
            model?: string;
            /** Operation Id */
            operation_id?: string | null;
            /** Preset Id */
            preset_id: string;
            /** Vision Mode */
            vision_mode?: ("auto" | "enabled" | "disabled") | null;
        };
        /** SkillSummary */
        SkillSummary: {
            /** Code */
            code: string;
            /** Counts */
            counts?: {
                [key: string]: components["schemas"]["SkillSummaryCountsValue"];
            };
            /** Evidence Count */
            evidence_count?: number;
            /** Evidence Status */
            evidence_status?: string;
            evidence_summary?: components["schemas"]["EvidenceSummary"] | null;
            /** Grade Band */
            grade_band: string | null;
            /** Joint Task Evidence */
            joint_task_evidence?: number;
            /** Label */
            label: string;
            /** Last Checked At */
            last_checked_at?: string | null;
            /** Mastery */
            mastery: number | null;
            /** Next Action */
            next_action?: string;
            /** Next Href */
            next_href?: string;
            /** Observation */
            observation?: string;
        };
        /** SkillSummaryCountsValue */
        SkillSummaryCountsValue: {
            /** Correct */
            correct: number;
            /** Incorrect */
            incorrect: number;
        };
        /** SourceRejection */
        SourceRejection: {
            /** Item Index */
            item_index: number;
            /**
             * Reason
             * @enum {string}
             */
            reason: "invalid_item" | "invalid_url" | "missing_identity" | "empty_excerpt" | "duplicate_item";
        };
        /** SourceSnapshot */
        SourceSnapshot: {
            attribution?: components["schemas"]["Attribution"] | null;
            /** Author */
            author: string | null;
            /** Content Id */
            content_id: string;
            /** Content Type */
            content_type: string;
            /**
             * Content Warnings
             * @default []
             */
            content_warnings?: string[];
            /** Duplicate Of */
            duplicate_of?: string | null;
            /**
             * Normalization
             * @default zhihu-highlight-v1
             * @enum {string}
             */
            normalization?: "zhihu-highlight-v1" | "public-text-v1";
            /** Original Url */
            original_url: string;
            /**
             * Provider
             * @default zhihu
             */
            provider?: "zhihu" | ("wikipedia" | "wikibooks" | "active_calculus" | "open_math_books");
            /** Raw Excerpt */
            raw_excerpt: string;
            /** Raw Excerpt Sha256 */
            raw_excerpt_sha256: string;
            /** Received Text Sha256 */
            received_text_sha256: string;
            /** Request Id */
            request_id: string;
            /** Retrieved At */
            retrieved_at: string;
            /**
             * Scope
             * @default search_excerpt
             * @enum {string}
             */
            scope?: "search_excerpt" | "page_excerpt" | "textbook_excerpt";
            /** Source Id */
            source_id: string;
            /** Text */
            text: string;
            /** Text Sha256 */
            text_sha256: string;
            /** Title */
            title: string;
            /**
             * Truncated
             * @default false
             */
            truncated?: boolean;
        };
        /** StudentExport */
        StudentExport: {
            /** Documents */
            documents: components["schemas"]["DesktopDocument"][];
            /** Memory */
            memory: components["schemas"]["DesktopMemory"][];
            meta: components["schemas"]["StudentExportMeta"];
            student_summary: components["schemas"]["StudentExportStudent_summary"];
        };
        /** StudentExportMeta */
        StudentExportMeta: {
            /** Exported At */
            exported_at: string;
            /** Schema Version */
            schema_version: string;
            /** Student Id */
            student_id: string;
        };
        /** StudentExportStudent_summary */
        StudentExportStudent_summary: {
            /** Active Misconceptions */
            active_misconceptions: components["schemas"]["ExportMisconception"][];
            /** Estimator Version */
            estimator_version: string;
            /** Item Error Observations */
            item_error_observations?: components["schemas"]["ItemErrorObservation"][];
            /** Learning Loop */
            learning_loop?: components["schemas"]["ExportLearningLoop"][];
            /** Model Status */
            model_status?: string;
            /** Projection Version */
            projection_version: number | null;
            /** Skills */
            skills: components["schemas"]["ExportSkill"][];
            /** Total Attempts */
            total_attempts: number;
        };
        /** StudentSummary */
        StudentSummary: {
            /** Active Misconceptions */
            active_misconceptions: number;
            coverage?: components["schemas"]["StudentSummaryCoverage"];
            evidence_summary?: components["schemas"]["EvidenceSummary"];
            /** Has Conversations */
            has_conversations?: boolean;
            /** Has Independent Evidence */
            has_independent_evidence?: boolean;
            /** Item Error Observations */
            item_error_observations?: components["schemas"]["ItemErrorObservation"][];
            /** Last Event Seq */
            last_event_seq?: number;
            /** Misconceptions */
            misconceptions?: components["schemas"]["StudentSummaryMisconceptionsItem"][];
            /** Model Status */
            model_status?: string;
            /** Review Observations */
            review_observations?: components["schemas"]["ReviewObservation"][];
            /** Schema Version */
            schema_version?: string;
            /** Skills */
            skills: components["schemas"]["SkillSummary"][];
            /** Total Attempts */
            total_attempts: number;
        };
        /** StudentSummaryCoverage */
        StudentSummaryCoverage: {
            /** Observed Skills */
            observed_skills: number;
            /** Supported Skills */
            supported_skills: number;
        };
        /** StudentSummaryMisconceptionsItem */
        StudentSummaryMisconceptionsItem: {
            /** Label */
            label: string;
            /** Last Seen At */
            last_seen_at: string | null;
            /** Rule Id */
            rule_id: string;
            /** Skill Ids */
            skill_ids: string[];
        };
        /** TestConnectionResult */
        TestConnectionResult: {
            /** Accepted */
            accepted?: boolean;
            /** Current Revision */
            current_revision?: number;
            /** Epoch */
            epoch?: string;
            /** Message */
            message: string;
            /** Operation Id */
            operation_id?: string;
            /** Persisted */
            persisted?: boolean;
            /** Persistence Error */
            persistence_error?: "config_write_failed" | "persistence_unavailable" | null;
            /** Provider Id */
            provider_id?: string;
            /** Resolved Model */
            resolved_model?: string;
            /** Revision */
            revision?: number;
            /** Status */
            status: "ok" | "error";
        };
        /** TutorSettings */
        TutorSettings: {
            /** Custom Instruction */
            custom_instruction: string;
            /** Personality */
            personality: string;
            /** Presets */
            presets: components["schemas"]["TutorSettingsPresetsItem"][];
        };
        /** TutorSettingsPresetsItem */
        TutorSettingsPresetsItem: {
            /** Id */
            id: string;
            /** Label */
            label: string;
        };
        /** TutorSettingsUpdate */
        TutorSettingsUpdate: {
            /**
             * Custom Instruction
             * @default
             */
            custom_instruction?: string;
            /**
             * Personality
             * @default patient
             */
            personality?: string;
        };
        /** UnverifiedComparison */
        UnverifiedComparison: {
            /** Proposed Relation */
            proposed_relation: string;
            /** Reading Question */
            reading_question: string;
            /** Span Ids */
            span_ids: [
                string,
                string
            ];
            /**
             * Status
             * @default unverified
             * @constant
             */
            status?: "unverified";
        };
        /** UnverifiedInterpretation */
        UnverifiedInterpretation: {
            /** Claim Id */
            claim_id: string;
            /**
             * Kind
             * @default model_interpretation
             * @constant
             */
            kind?: "model_interpretation";
            /**
             * Mathematical Status
             * @default not_evaluated
             * @constant
             */
            mathematical_status?: "not_evaluated";
            /**
             * Semantic Support
             * @default unknown
             * @constant
             */
            semantic_support?: "unknown";
            /** Span Ids */
            span_ids: string[];
            /** Text */
            text: string;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    get_cycle_api_v2_math_tutor_cycles__cycle_id__get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                cycle_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_backup_endpoint_api_v2_math_tutor_desktop_backup_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BackupActionResultVariant1"] | components["schemas"]["BackupActionResultVariant2"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_backup_endpoint_api_v2_math_tutor_desktop_backup_restore_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BackupPathRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BackupRestoreResultVariant1"] | components["schemas"]["BackupRestoreResultVariant2"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    verify_backup_endpoint_api_v2_math_tutor_desktop_backup_verify_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BackupPathRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BackupVerifyResultVariant1"] | components["schemas"]["BackupVerifyResultVariant2"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_backups_endpoint_api_v2_math_tutor_desktop_backups_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BackupsList"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bootstrap_api_v2_math_tutor_desktop_bootstrap_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BootstrapPayload"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    attach_conversation_document_api_v2_math_tutor_desktop_conversations__conversation_id__documents__document_id__post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                conversation_id: string;
                document_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    detach_conversation_document_api_v2_math_tutor_desktop_conversations__conversation_id__documents__document_id__delete: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                conversation_id: string;
                document_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_conversation_folder_api_v2_math_tutor_desktop_conversations__conversation_id__export_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    conversation_resources_api_v2_math_tutor_desktop_conversations__conversation_id__resources_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    turn_diagnostics_api_v2_math_tutor_desktop_diagnostics_turns_get: {
        parameters: {
            query?: {
                status?: string | null;
                limit?: number;
            };
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_documents_api_v2_math_tutor_desktop_documents_get: {
        parameters: {
            query?: {
                conversation_id?: string;
            };
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopDocument"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    import_document_api_v2_math_tutor_desktop_documents_import_post: {
        parameters: {
            query?: {
                conversation_id?: string;
            };
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_import_document_api_v2_math_tutor_desktop_documents_import_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopDocument"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    pick_document_api_v2_math_tutor_desktop_documents_pick_post: {
        parameters: {
            query?: {
                conversation_id?: string;
            };
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_document_api_v2_math_tutor_desktop_documents__document_id__get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                document_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopDocument"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reparse_document_api_v2_math_tutor_desktop_documents__document_id__put: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                document_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopDocument"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_document_api_v2_math_tutor_desktop_documents__document_id__delete: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                document_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rename_document_api_v2_math_tutor_desktop_documents__document_id__patch: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                document_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DocumentRename"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopDocument"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_document_retrieval_api_v2_math_tutor_desktop_documents__document_id__retrieval_patch: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                document_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RetrievalToggle"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopDocument"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_document_scope_setting_api_v2_math_tutor_desktop_documents__document_id__scope_patch: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                document_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DocumentScopeInput"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopDocument"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_question_bank_api_v2_math_tutor_desktop_exercise_bank_get: {
        parameters: {
            query?: {
                stage?: string | null;
            };
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_question_bank_point_api_v2_math_tutor_desktop_exercise_bank_points__code__get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                code: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    configuration_api_v2_math_tutor_desktop_exploration_configuration_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExplorationConfiguration"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    configure_api_v2_math_tutor_desktop_exploration_configuration_put: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExplorationCredential"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExplorationConfiguration"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    disconnect_api_v2_math_tutor_desktop_exploration_configuration_delete: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExplorationConfiguration"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    inquiries_api_v2_math_tutor_desktop_exploration_inquiries_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InquiryList"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_api_v2_math_tutor_desktop_exploration_inquiries_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InquiryCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExplorationView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_api_v2_math_tutor_desktop_exploration_inquiries__inquiry_id__get: {
        parameters: {
            query?: {
                language?: "zh" | "en";
            };
            header?: {
                Authorization?: string | null;
            };
            path: {
                inquiry_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExplorationView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_api_v2_math_tutor_desktop_exploration_inquiries__inquiry_id__delete: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                inquiry_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InquiryList"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    explanation_api_v2_math_tutor_desktop_exploration_inquiries__inquiry_id__explanation_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                inquiry_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InquiryExplanation"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExplorationView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    organize_api_v2_math_tutor_desktop_exploration_inquiries__inquiry_id__organize_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                inquiry_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InquiryOperation"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExplorationView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reflection_api_v2_math_tutor_desktop_exploration_inquiries__inquiry_id__reflection_put: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                inquiry_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InquiryReflection"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExplorationView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    respond_api_v2_math_tutor_desktop_exploration_inquiries__inquiry_id__response_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                inquiry_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InquiryResponse"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExplorationView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    search_library_api_v2_math_tutor_desktop_exploration_library_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LibraryQuery"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LibraryExcerpt"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    initial_assessment_api_v2_math_tutor_desktop_initial_assessment_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    answer_initial_assessment_api_v2_math_tutor_desktop_initial_assessment_answer_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InitialAnswer"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resume_initial_assessment_api_v2_math_tutor_desktop_initial_assessment_resume_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InitialResume"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    skip_initial_assessment_api_v2_math_tutor_desktop_initial_assessment_skip_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InitialRun"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    start_initial_assessment_api_v2_math_tutor_desktop_initial_assessment_start_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    learning_loop_api_v2_math_tutor_desktop_learning_loop_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    answer_learning_loop_api_v2_math_tutor_desktop_learning_loop_answer_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LearningLoopAnswer"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    help_learning_loop_api_v2_math_tutor_desktop_learning_loop_help_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LearningLoopAction"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    start_learning_loop_api_v2_math_tutor_desktop_learning_loop_start_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LearningLoopStart"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_memory_api_v2_math_tutor_desktop_memory_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopMemory"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_memory_api_v2_math_tutor_desktop_memory_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MemoryCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopMemory"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_memory_api_v2_math_tutor_desktop_memory__memory_id__put: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                memory_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MemoryUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopMemory"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_memory_api_v2_math_tutor_desktop_memory__memory_id__delete: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                memory_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    confirm_memory_api_v2_math_tutor_desktop_memory__memory_id__confirm_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                memory_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["MemoryConfirmation"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopMemory"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_memory_retrieval_api_v2_math_tutor_desktop_memory__memory_id__retrieval_patch: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                memory_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RetrievalToggle"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopMemory"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    test_model_api_v2_math_tutor_desktop_model_test_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ConfigOperation"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModelTestResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_educational_history_api_v2_math_tutor_desktop_privacy_educational_history_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EducationalHistoryResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_encryption_api_v2_math_tutor_desktop_privacy_encryption_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_encryption_api_v2_math_tutor_desktop_privacy_encryption_put: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EncryptionUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reveal_recovery_key_api_v2_math_tutor_desktop_privacy_encryption_recovery_key_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_student_data_api_v2_math_tutor_desktop_privacy_export_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StudentExport"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    purge_documents_api_v2_math_tutor_desktop_privacy_purge_documents_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PurgeDocumentsResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    purge_memory_api_v2_math_tutor_desktop_privacy_purge_memory_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PurgeMemoryResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rebuild_indexes_api_v2_math_tutor_desktop_privacy_rebuild_indexes_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RebuildIndexesResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    recompute_api_v2_math_tutor_desktop_privacy_recompute_profile_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    readiness_api_v2_math_tutor_desktop_readiness_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Readiness"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    recommendations_api_v2_math_tutor_desktop_recommendations_get: {
        parameters: {
            query?: {
                language?: "zh" | "en";
            };
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_api_v2_math_tutor_desktop_recommendations_delete: {
        parameters: {
            query?: {
                language?: "zh" | "en";
            };
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    configure_api_v2_math_tutor_desktop_recommendations_configuration_put: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecommendationSettings"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    start_api_v2_math_tutor_desktop_recommendations_start_post: {
        parameters: {
            query?: {
                language?: "zh" | "en";
            };
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_settings_api_v2_math_tutor_desktop_settings_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopSettings"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_settings_api_v2_math_tutor_desktop_settings_put: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SettingsUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsSaveResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_api_key_api_v2_math_tutor_desktop_settings_api_key_delete: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ConfigOperation"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DesktopSettings"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_cost_settings_api_v2_math_tutor_desktop_settings_cost_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CostSettings"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_cost_settings_api_v2_math_tutor_desktop_settings_cost_put: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CostSettingsUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CostSettings"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_embedding_settings_api_v2_math_tutor_desktop_settings_embedding_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EmbeddingSettings"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_embedding_settings_api_v2_math_tutor_desktop_settings_embedding_put: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EmbeddingSettingsUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EmbeddingSettings"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_embedding_api_key_api_v2_math_tutor_desktop_settings_embedding_api_key_delete: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EmbeddingSettings"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_local_embedding_model_api_v2_math_tutor_desktop_settings_embedding_local_download_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocalEmbeddingDownloadRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EmbeddingSettings"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_local_embedding_model_api_v2_math_tutor_desktop_settings_embedding_local__model_id__delete: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                model_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EmbeddingSettings"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    test_embedding_connection_api_v2_math_tutor_desktop_settings_embedding_test_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EmbeddingTestResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_learner_settings_api_v2_math_tutor_desktop_settings_learner_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_learner_settings_api_v2_math_tutor_desktop_settings_learner_put: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LearnerUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_models_api_v2_math_tutor_desktop_settings_models_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": string[];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    skip_provider_onboarding_api_v2_math_tutor_desktop_settings_onboarding_skip_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ConfigOperation"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_presets_api_v2_math_tutor_desktop_settings_presets_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderPreset"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    test_connection_api_v2_math_tutor_desktop_settings_test_connection_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ConfigOperation"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TestConnectionResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_tutor_settings_api_v2_math_tutor_desktop_settings_tutor_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TutorSettings"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_tutor_settings_api_v2_math_tutor_desktop_settings_tutor_put: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TutorSettingsUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TutorSettings"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    evidence_api_v2_math_tutor_desktop_student_evidence_get: {
        parameters: {
            query?: {
                skill_id?: string | null;
                cycle_id?: string | null;
                cursor?: number | null;
            };
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EvidencePage"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    exclude_api_v2_math_tutor_desktop_student_evidence__event_id__exclude_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                event_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    student_summary_api_v2_math_tutor_desktop_student_summary_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StudentSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_offers_api_v2_math_tutor_offers_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PracticeOffer"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    offer_feedback_api_v2_math_tutor_offers__offer_id__feedback_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                offer_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OfferFeedbackInput"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resume_offer_api_v2_math_tutor_offers__offer_id__resume_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                offer_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_sessions_api_v2_math_tutor_sessions_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    }[];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_session_api_v2_math_tutor_sessions_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConversationCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_session_api_v2_math_tutor_sessions__session_id__get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                session_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    trash_session_api_v2_math_tutor_sessions__session_id__delete: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                session_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_trash_api_v2_math_tutor_trash_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    purge_session_api_v2_math_tutor_trash__session_id__delete: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                session_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_session_api_v2_math_tutor_trash__session_id__restore_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                session_id: string;
            };
            cookie?: {
                dt_token?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
