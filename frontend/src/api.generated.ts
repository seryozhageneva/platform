export interface paths {
    "/api/v1/assignments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Назначить урок ученику */
        post: operations["assign_api_v1_assignments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Logout */
        post: operations["logout_api_v1_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read Me */
        get: operations["read_me_api_v1_auth_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/student": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Login Student */
        post: operations["login_student_api_v1_auth_student_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/teacher": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Login Teacher */
        post: operations["login_teacher_api_v1_auth_teacher_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/blocks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Каталог блоков */
        get: operations["list_blocks_api_v1_blocks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Сервер работает */
        get: operations["health_api_v1_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/pipelines": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Свои пайплайны */
        get: operations["list_pipelines_api_v1_pipelines_get"];
        put?: never;
        /** Сохранить новый пайплайн */
        post: operations["create_pipeline_api_v1_pipelines_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/pipelines/{pipeline_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Пайплайн с графом последней версии */
        get: operations["get_pipeline_api_v1_pipelines__pipeline_id__get"];
        /** Сохранить пайплайн новой версией */
        put: operations["save_pipeline_version_api_v1_pipelines__pipeline_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/pipelines/{pipeline_id}/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Запустить пайплайн вручную */
        post: operations["launch_manually_api_v1_pipelines__pipeline_id__runs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Свои запуски */
        get: operations["list_runs_api_v1_runs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Состояние запуска */
        get: operations["get_run_api_v1_runs__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{run_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Журнал событий запуска */
        get: operations["get_run_events_api_v1_runs__run_id__events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{run_id}/responses": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Ответить запуску, который ждёт человека */
        post: operations["respond_api_v1_runs__run_id__responses_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/student/lessons": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Список назначенных уроков */
        get: operations["list_lessons_api_v1_student_lessons_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/student/lessons/{lesson_id}/open": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Открыть или продолжить урок */
        post: operations["open_student_lesson_api_v1_student_lessons__lesson_id__open_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/student/lessons/{lesson_id}/responses": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Ответить или попросить подсказку */
        post: operations["respond_to_lesson_api_v1_student_lessons__lesson_id__responses_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/students": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Students */
        get: operations["list_students_api_v1_students_get"];
        put?: never;
        /** Create Student */
        post: operations["create_student_api_v1_students_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/students/{student_id}/link": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Issue Link */
        post: operations["issue_link_api_v1_students__student_id__link_post"];
        /** Revoke Link */
        delete: operations["revoke_link_api_v1_students__student_id__link_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tasks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Свои задачи; незаданное условие не учитывается */
        get: operations["find_tasks_api_v1_tasks_get"];
        put?: never;
        /** Добавить задачу в банк */
        post: operations["create_task_api_v1_tasks_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tasks/{task_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Одна своя задача */
        get: operations["get_task_api_v1_tasks__task_id__get"];
        /** Исправить задачу или подтвердить черновик */
        put: operations["update_task_api_v1_tasks__task_id__put"];
        post?: never;
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
        /** Answer */
        Answer: {
            file?: components["schemas"]["FileRef"] | null;
            form: components["schemas"]["AnswerForm"];
            /** Task Id */
            task_id: string;
            /** Text */
            text?: string | null;
        };
        /**
         * AnswerForm
         * @enum {string}
         */
        AnswerForm: "text" | "formula" | "code" | "photo";
        /**
         * AnswerFormResponse
         * @description Свободного чата нет: ученик либо отвечает, либо просит подсказку.
         */
        AnswerFormResponse: {
            /**
             * Action
             * @enum {string}
             */
            action: "answer" | "hint";
            answer?: components["schemas"]["Answer"] | null;
        };
        /** AssignmentIn */
        AssignmentIn: {
            /** Params */
            params?: {
                [key: string]: unknown;
            };
            /**
             * Pipeline Id
             * Format: uuid
             */
            pipeline_id: string;
            /**
             * Student Id
             * Format: uuid
             */
            student_id: string;
        };
        /** AssignmentOut */
        AssignmentOut: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
        };
        /** BlockCatalogItem */
        BlockCatalogItem: {
            category: components["schemas"]["Category"];
            /** Config */
            config: {
                [key: string]: unknown;
            };
            /** Description */
            description: string;
            /** Id */
            id: string;
            /** Inputs */
            inputs: components["schemas"]["InputPort"][];
            /** Name */
            name: string;
            /** Outcomes */
            outcomes: string[];
            /** Outputs */
            outputs: components["schemas"]["OutputPort"][];
            /** Side Effects */
            side_effects: boolean;
        };
        /**
         * BlockNode
         * @description Блок со своими настройками и привязками входов: имя входа -> откуда взять данные.
         */
        BlockNode: {
            /** Block */
            block: string;
            /**
             * Config
             * @default {}
             */
            config: {
                [key: string]: unknown;
            };
            /** Id */
            id: string;
            /**
             * Inputs
             * @default {}
             */
            inputs: {
                [key: string]: string | string[];
            };
            limit?: components["schemas"]["Limit"] | null;
            /**
             * Title
             * @default
             */
            title: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "block";
        };
        /**
         * Body
         * @description Тело «для каждого»: маленький граф, который начинается с узла `start`.
         */
        Body: {
            /** Nodes */
            nodes: (components["schemas"]["BlockNode"] | components["schemas"]["SwitchNode"] | components["schemas"]["ForEachNode"])[];
            /** Start */
            start: string;
            /**
             * Transitions
             * @default []
             */
            transitions: components["schemas"]["Transition"][];
        };
        /**
         * Category
         * @description Семь категорий блоков. Триггер — узел ядра, манифеста у него нет.
         * @enum {string}
         */
        Category: "source" | "transform" | "student" | "check" | "ai_process" | "approval" | "sink";
        /**
         * CheckMethod
         * @description Способ проверки записан в самой задаче.
         * @enum {string}
         */
        CheckMethod: "short_answer" | "code" | "long_answer";
        /**
         * ErrorOut
         * @description Ответ на запрос, который не выполнен: что случилось и список причин.
         */
        ErrorOut: {
            /** Message */
            message: string;
            /**
             * Problems
             * @default []
             */
            problems: components["schemas"]["ProblemOut"][];
        };
        /**
         * EventOut
         * @description Запись журнала событий запуска.
         */
        EventOut: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Data */
            data: {
                [key: string]: unknown;
            };
            /** Id */
            id: number;
            /** Node Id */
            node_id: string;
            /** Type */
            type: string;
        };
        /**
         * FileKind
         * @enum {string}
         */
        FileKind: "document" | "code" | "image" | "other";
        /**
         * FileRef
         * @description Тип `File`: ссылка на файл в хранилище, а не его содержимое.
         */
        FileRef: {
            /** Id */
            id: string;
            kind: components["schemas"]["FileKind"];
            /** Media Type */
            media_type: string;
            /**
             * Meta
             * @default {}
             */
            meta: {
                [key: string]: unknown;
            };
            /** Name */
            name: string;
            /** Size */
            size?: number | null;
            /** Student Id */
            student_id?: string | null;
        };
        /**
         * ForEachNode
         * @description «Для каждого»: выполнить `body` отдельно для каждого элемента списка `over`.
         *
         *     Внутри тела текущий элемент доступен как выход `item` этого узла. `collect` говорит,
         *     что собрать в выход `results`: одно значение или запись из нескольких (тогда `as` —
         *     название записи, по которому её поля потом читаются как «узел.порт.поле»).
         */
        ForEachNode: {
            /** As */
            as?: string | null;
            body: components["schemas"]["Body"];
            /** Collect */
            collect?: string | {
                [key: string]: string | string[];
            } | null;
            /** Id */
            id: string;
            limit?: components["schemas"]["Limit"] | null;
            /** Over */
            over: string;
            /**
             * Title
             * @default
             */
            title: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "for_each";
        };
        /** Hint */
        Hint: {
            /** Level */
            level: number;
            /** Task Id */
            task_id: string;
            /** Text */
            text: string;
        };
        /**
         * InputPort
         * @description Вход блока. Необязательный вход может остаться без данных.
         */
        InputPort: {
            /**
             * List
             * @default false
             */
            list: boolean;
            /** Name */
            name: string;
            /** Of */
            of?: string | null;
            /**
             * Required
             * @default true
             */
            required: boolean;
            /** Schema */
            schema?: {
                [key: string]: unknown;
            } | null;
            /** Title */
            title: string;
            type: components["schemas"]["PortType"];
        };
        /**
         * Launch
         * @description Один способ запуска пайплайна.
         */
        Launch: {
            /** Cron */
            cron?: string | null;
            /**
             * Settings
             * @default {}
             */
            settings: {
                [key: string]: unknown;
            };
            type: components["schemas"]["TriggerType"];
        };
        /**
         * LaunchRequest
         * @description Значения параметров пайплайна; незаполненные берутся по умолчанию.
         */
        LaunchRequest: {
            /** Expected Version */
            expected_version?: number | null;
            /**
             * Params
             * @default {}
             */
            params: {
                [key: string]: unknown;
            };
        };
        /** LessonOut */
        LessonOut: {
            screen?: components["schemas"]["LessonScreen"] | null;
            status: components["schemas"]["RunStatus"];
        };
        /** LessonResponseIn */
        LessonResponseIn: {
            /** Node Id */
            node_id: string;
            response: components["schemas"]["AnswerFormResponse"];
            /** Revision */
            revision: string;
        };
        /** LessonScreen */
        LessonScreen: {
            /**
             * Can Ask Hint
             * @default true
             */
            can_ask_hint: boolean;
            /** Forms */
            forms: components["schemas"]["AnswerForm"][];
            hint?: components["schemas"]["Hint"] | null;
            /** Node Id */
            node_id: string;
            /** Revision */
            revision: string;
            /** Statement */
            statement: string;
            /** Task Id */
            task_id: string;
        };
        /** LessonSummary */
        LessonSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Name */
            name: string;
        };
        /**
         * Limit
         * @description Ограничитель: сколько раз узел можно пройти и куда идти, когда попытки кончились.
         */
        Limit: {
            /** Max */
            max: number | components["schemas"]["ParamRef"];
            /** Otherwise */
            otherwise?: string | null;
            /** Reset On */
            reset_on?: string | null;
        };
        /**
         * OutputPort
         * @description Выход блока.
         *
         *     У универсальных блоков тип выхода вычисляется для каждого узла: `same_as` — повторяет
         *     тип того, что подано на указанный вход; `from_config` — записан в указанной настройке.
         */
        OutputPort: {
            /** From Config */
            from_config?: string | null;
            /**
             * List
             * @default false
             */
            list: boolean;
            /** Name */
            name: string;
            /** Of */
            of?: string | null;
            /** Same As */
            same_as?: string | null;
            /** Schema */
            schema?: {
                [key: string]: unknown;
            } | null;
            /** Title */
            title: string;
            type: components["schemas"]["PortType"];
        };
        /**
         * Param
         * @description Значение, которое преподаватель заполняет при назначении, а не зашивает в схему.
         */
        Param: {
            /** Default */
            default?: unknown;
            /** Name */
            name: string;
            /** Title */
            title: string;
            type: components["schemas"]["ParamType"];
        };
        /**
         * ParamRef
         * @description Ссылка на параметр пайплайна: `{"$param": "topic"}`.
         */
        ParamRef: {
            /** $Param */
            $param: string;
        };
        /**
         * ParamType
         * @enum {string}
         */
        ParamType: "string" | "integer" | "number" | "boolean";
        /** Pipeline */
        Pipeline: {
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Format
             * @default 1
             * @constant
             */
            format: 1;
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Nodes */
            nodes: (components["schemas"]["TriggerNode"] | components["schemas"]["BlockNode"] | components["schemas"]["SwitchNode"] | components["schemas"]["ForEachNode"])[];
            /**
             * Params
             * @default []
             */
            params: components["schemas"]["Param"][];
            /**
             * Transitions
             * @default []
             */
            transitions: components["schemas"]["Transition"][];
        };
        /** PipelineDetail */
        PipelineDetail: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            graph: components["schemas"]["Pipeline"];
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Latest Version */
            latest_version: number;
            /** Name */
            name: string;
            /** Slug */
            slug: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** PipelineSaved */
        PipelineSaved: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Version */
            version: number;
            /**
             * Warnings
             * @default []
             */
            warnings: components["schemas"]["ProblemOut"][];
        };
        /** PipelineSummary */
        PipelineSummary: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Latest Version */
            latest_version: number;
            /** Name */
            name: string;
            /** Slug */
            slug: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /**
         * PortType
         * @description Восемь видов данных, которые ходят между блоками.
         * @enum {string}
         */
        PortType: "Event" | "Data" | "File" | "Text" | "Task" | "Answer" | "Verdict" | "Hint";
        /**
         * ProblemOut
         * @description Одна причина отказа или предупреждение.
         */
        ProblemOut: {
            /** Code */
            code: string;
            /** Message */
            message: string;
            /** Node */
            node?: string | null;
        };
        /**
         * ResponseIn
         * @description Ответ человека запуску на паузе: на каком узле и что он ввёл на экране.
         */
        ResponseIn: {
            /** Approval Id */
            approval_id?: string | null;
            /** Node Id */
            node_id: string;
            /** Response */
            response: {
                [key: string]: unknown;
            };
        };
        /**
         * RunOut
         * @description Состояние запуска без данных портов: что из них показывать, решает кабинет.
         */
        RunOut: {
            /** Current */
            current: string[];
            /** Error */
            error: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Params */
            params: {
                [key: string]: unknown;
            };
            /**
             * Pipeline Id
             * Format: uuid
             */
            pipeline_id: string;
            /** Pipeline Version */
            pipeline_version: number;
            status: components["schemas"]["RunStatus"];
            /** Waiting */
            waiting: components["schemas"]["WaitingOut"][];
        };
        /**
         * RunStatus
         * @enum {string}
         */
        RunStatus: "running" | "waiting" | "done" | "error";
        /** RunSummary */
        RunSummary: {
            /** Current */
            current: string[];
            /** Error */
            error: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Pipeline Id
             * Format: uuid
             */
            pipeline_id: string;
            /** Pipeline Name */
            pipeline_name: string;
            /** Pipeline Version */
            pipeline_version: number;
            status: components["schemas"]["RunStatus"];
            /** Student Name */
            student_name: string | null;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Waiting */
            waiting: components["schemas"]["RunWaitingSummary"][];
        };
        /** RunWaitingSummary */
        RunWaitingSummary: {
            /** Node Id */
            node_id: string;
            /**
             * Who
             * @enum {string}
             */
            who: "student" | "teacher";
        };
        /**
         * ScreenType
         * @enum {string}
         */
        ScreenType: "answer_form" | "confirm_recognized" | "review_table" | "review_document";
        /** StudentCreate */
        StudentCreate: {
            /** Name */
            name: string;
        };
        /** StudentLinkOut */
        StudentLinkOut: {
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /** Token */
            token: string;
        };
        /** StudentLogin */
        StudentLogin: {
            /**
             * Token
             * Format: password
             */
            token: string;
        };
        /** StudentOut */
        StudentOut: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Link Expires At */
            link_expires_at: string | null;
            /** Name */
            name: string;
        };
        /**
         * SwitchNode
         * @description Развилка по значению: исход узла — значение поля `field` у данных `value`.
         */
        SwitchNode: {
            /** Field */
            field: string;
            /** Id */
            id: string;
            limit?: components["schemas"]["Limit"] | null;
            /**
             * Title
             * @default
             */
            title: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "switch";
            /** Value */
            value: string;
        };
        /**
         * TaskIn
         * @description Задача банка, как её присылает преподаватель (ADR 0015).
         */
        TaskIn: {
            /** Answer */
            answer?: string | null;
            check_method: components["schemas"]["CheckMethod"];
            /** Difficulty */
            difficulty: number;
            /** Rubric */
            rubric?: string | null;
            /** Solution */
            solution?: string | null;
            /**
             * Statement
             * @description Условие: Markdown и LaTeX
             */
            statement: string;
            /** @default approved */
            status: components["schemas"]["TaskStatus"];
            /** Subject */
            subject: string;
            /** Tests */
            tests?: string | null;
            /** Topic */
            topic: string;
        };
        /**
         * TaskOut
         * @description Задача банка в ответе: поля, номер и время.
         */
        TaskOut: {
            /** Answer */
            answer?: string | null;
            check_method: components["schemas"]["CheckMethod"];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Difficulty */
            difficulty: number;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Rubric */
            rubric?: string | null;
            /** Solution */
            solution?: string | null;
            /**
             * Statement
             * @description Условие: Markdown и LaTeX
             */
            statement: string;
            /** @default approved */
            status: components["schemas"]["TaskStatus"];
            /** Subject */
            subject: string;
            /** Tests */
            tests?: string | null;
            /** Topic */
            topic: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /**
         * TaskStatus
         * @description В урок попадают только подтверждённые задачи.
         * @enum {string}
         */
        TaskStatus: "draft" | "approved";
        /** TeacherLogin */
        TeacherLogin: {
            /** Email */
            email: string;
            /**
             * Password
             * Format: password
             */
            password: string;
        };
        /**
         * Transition
         * @description Переход «после узла `from` при исходе `when` выполнить узел `to`».
         *
         *     Переход без `when` срабатывает при любом исходе, для которого нет своего перехода.
         */
        Transition: {
            /** From */
            from: string;
            /** To */
            to: string;
            /** When */
            when?: string | null;
        };
        /**
         * TriggerNode
         * @description Стартовый узел. У него один выход — `event` типа Event.
         */
        TriggerNode: {
            /** Id */
            id: string;
            /** Launches */
            launches: components["schemas"]["Launch"][];
            /**
             * Title
             * @default
             */
            title: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "trigger";
        };
        /**
         * TriggerType
         * @description Способы запуска пайплайна.
         * @enum {string}
         */
        TriggerType: "manual" | "student" | "schedule" | "moodle_event";
        /** UserOut */
        UserOut: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Name */
            name: string;
            /**
             * Role
             * @enum {string}
             */
            role: "teacher" | "student";
        };
        /** WaitingOut */
        WaitingOut: {
            /** Approval Id */
            approval_id?: string | null;
            /** Data */
            data: {
                [key: string]: unknown;
            };
            /** Node Id */
            node_id: string;
            screen: components["schemas"]["ScreenType"];
            /** Who */
            who: string;
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
    assign_api_v1_assignments_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssignmentIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssignmentOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    logout_api_v1_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    read_me_api_v1_auth_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    login_student_api_v1_auth_student_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StudentLogin"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    login_teacher_api_v1_auth_teacher_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TeacherLogin"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    list_blocks_api_v1_blocks_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BlockCatalogItem"][];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    health_api_v1_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
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
                        [key: string]: string;
                    };
                };
            };
        };
    };
    list_pipelines_api_v1_pipelines_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PipelineSummary"][];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    create_pipeline_api_v1_pipelines_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Pipeline"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PipelineSaved"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    get_pipeline_api_v1_pipelines__pipeline_id__get: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path: {
                pipeline_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PipelineDetail"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    save_pipeline_version_api_v1_pipelines__pipeline_id__put: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path: {
                pipeline_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Pipeline"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PipelineSaved"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    launch_manually_api_v1_pipelines__pipeline_id__runs_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path: {
                pipeline_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["LaunchRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Очередь запусков недоступна */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    list_runs_api_v1_runs_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunSummary"][];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    get_run_api_v1_runs__run_id__get: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    get_run_events_api_v1_runs__run_id__events_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EventOut"][];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    respond_api_v1_runs__run_id__responses_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResponseIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Пауза изменилась или запуск уже обновляется */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сервер запусков занят */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    list_lessons_api_v1_student_lessons_get: {
        parameters: {
            query?: never;
            header: {
                "X-Expected-Account": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LessonSummary"][];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    open_student_lesson_api_v1_student_lessons__lesson_id__open_post: {
        parameters: {
            query?: never;
            header: {
                "X-Expected-Account": string;
            };
            path: {
                lesson_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LessonOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сервер уроков занят */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    respond_to_lesson_api_v1_student_lessons__lesson_id__responses_post: {
        parameters: {
            query?: never;
            header: {
                "X-Expected-Account": string;
            };
            path: {
                lesson_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LessonResponseIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LessonOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сервер уроков занят */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    list_students_api_v1_students_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StudentOut"][];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    create_student_api_v1_students_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StudentCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StudentOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    issue_link_api_v1_students__student_id__link_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path: {
                student_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StudentLinkOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    revoke_link_api_v1_students__student_id__link_delete: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path: {
                student_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    find_tasks_api_v1_tasks_get: {
        parameters: {
            query?: {
                difficulty?: number | null;
                /** @description Без статуса — и черновики, и подтверждённые */
                status?: components["schemas"]["TaskStatus"] | null;
                subject?: string | null;
                topic?: string | null;
            };
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskOut"][];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    create_task_api_v1_tasks_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TaskIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    get_task_api_v1_tasks__task_id__get: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    update_task_api_v1_tasks__task_id__put: {
        parameters: {
            query?: never;
            header?: {
                "X-Expected-Account"?: string | null;
            };
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TaskIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskOut"];
                };
            };
            /** @description Не сказано, кто спрашивает */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Действие недоступно */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Не найдено среди своих записей */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Сеанс сменился */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
            /** @description Запрос не принят: причины — в `problems` */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
}
