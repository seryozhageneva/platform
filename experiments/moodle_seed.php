<?php
// Наполняет тестовый Moodle выдуманными данными (задача 23, ADR 0028; оценки — задача 27,
// ADR 0034).
//
// Запускается внутри контейнера Moodle скриптом experiments/moodle_setup.py — вручную его
// вызывать не нужно. Повторный запуск ничего не дублирует: найденное берётся как есть.
//
// Что появляется:
// - веб-сервисы REST и сервис «platform» с функциями чтения курсов, сдач и оценок и
//   функцией выставления оценки;
// - пользователь platform_reader — преподаватель курса, от его имени ходит платформа
//   (имя осталось с задачи 23: с задачи 27 он и ставит оценки);
// - курс PLATFORM-TEST с заданием «Контрольная работа» (файлы, черновики разрешены,
//   оценка до 100 баллов, комментарий к оценке);
// - четыре выдуманных студента: трое сдали файл, четвёртый оставил черновик.
//
// На вход — путь к папке с файлами работ. На выход — одна строка JSON с номерами курса и
// задания, адресом сайта и токеном. Токен печатается только сюда: его читает программа.

define('CLI_SCRIPT', true);

require('/var/www/html/config.php');
require_once($CFG->libdir . '/clilib.php');
require_once($CFG->libdir . '/testing/generator/lib.php');
require_once($CFG->dirroot . '/webservice/lib.php');
require_once($CFG->dirroot . '/mod/assign/locallib.php');

[$options] = cli_get_params(['files' => '']);
$filesdir = rtrim($options['files'], '/');
if ($filesdir === '' || !is_dir($filesdir)) {
    cli_error('нужен --files=папка с файлами работ');
}

\core\session\manager::set_user(get_admin());
$generator = new testing_data_generator();
$system = context_system::instance();

// --- Веб-сервисы ---
set_config('enablewebservices', 1);
set_config('webserviceprotocols', 'rest');

$functions = [
    'core_webservice_get_site_info',
    'mod_assign_get_assignments',
    'mod_assign_get_submissions',
    'mod_assign_save_grade',
    // Чтение оценки и комментария — для проверки, что оценка дошла (тесты и ручная проверка).
    'mod_assign_get_grades',
    'mod_assign_get_submission_status',
];
$manager = new webservice();
$service = $DB->get_record('external_services', ['shortname' => 'platform']);
if (!$service) {
    $serviceid = $manager->add_external_service((object) [
        'name' => 'Платформа учебных пайплайнов',
        'shortname' => 'platform',
        'enabled' => 1,
        'restrictedusers' => 0,
        'downloadfiles' => 1,
        'uploadfiles' => 0,
        'requiredcapability' => '',
    ]);
    $service = $DB->get_record('external_services', ['id' => $serviceid], '*', MUST_EXIST);
}
// Функции добавляются и в уже созданный сервис: Moodle, наполненный до задачи 27, получает
// функции оценок при повторном запуске.
foreach ($functions as $function) {
    if (!$manager->service_function_exists($function, $service->id)) {
        $manager->add_external_function_to_service($function, $service->id);
    }
}

// --- Пользователь платформы и его права на веб-сервис ---
$reader = $DB->get_record('user', ['username' => 'platform_reader', 'deleted' => 0]);
if (!$reader) {
    $reader = $generator->create_user([
        'username' => 'platform_reader',
        'firstname' => 'Платформа',
        'lastname' => 'Чтение',
        'email' => 'platform.reader@example.test',
        'auth' => 'manual',
    ]);
}
$roleid = $DB->get_field('role', 'id', ['shortname' => 'platformws']);
if (!$roleid) {
    $roleid = create_role('Доступ платформы к веб-сервису', 'platformws', '');
    set_role_contextlevels($roleid, [CONTEXT_SYSTEM]);
    assign_capability('webservice/rest:use', CAP_ALLOW, $roleid, $system->id);
}
role_assign($roleid, $reader->id, $system->id);

// --- Курс, задание, студенты ---
$course = $DB->get_record('course', ['shortname' => 'PLATFORM-TEST']);
if (!$course) {
    $course = $generator->create_course([
        'fullname' => 'Тестовый курс платформы',
        'shortname' => 'PLATFORM-TEST',
    ]);
}
$generator->enrol_user($reader->id, $course->id, 'editingteacher');

$assignment = $DB->get_record('assign', ['course' => $course->id, 'name' => 'Контрольная работа']);
if (!$assignment) {
    $assignment = $generator->create_module('assign', [
        'course' => $course->id,
        'name' => 'Контрольная работа',
        'assignsubmission_file_enabled' => 1,
        'assignsubmission_file_maxfiles' => 3,
        'assignsubmission_file_maxsizebytes' => 10 * 1024 * 1024,
        'assignsubmission_onlinetext_enabled' => 0,
        'submissiondrafts' => 1,
        'assignfeedback_comments_enabled' => 1,
        'grade' => 100,
    ]);
}
[$course, $cm] = get_course_and_cm_from_instance($assignment->id, 'assign');
$assign = new assign(context_module::instance($cm->id), $cm, $course);
// Комментарий к оценке включается и у задания, созданного до задачи 27.
$comments = $assign->get_feedback_plugin_by_type('comments');
if (!$comments->is_enabled()) {
    $comments->enable();
}

// Студент и его файл; черновик — работа не сдана, платформа её не должна видеть.
$students = [
    ['student1', 'Студент', 'Первый', 'work1.pdf', ASSIGN_SUBMISSION_STATUS_SUBMITTED],
    ['student2', 'Студент', 'Второй', 'work2.docx', ASSIGN_SUBMISSION_STATUS_SUBMITTED],
    ['student3', 'Студент', 'Третий', 'solution.py', ASSIGN_SUBMISSION_STATUS_SUBMITTED],
    ['student4', 'Студент', 'Четвёртый', 'draft.pdf', ASSIGN_SUBMISSION_STATUS_DRAFT],
];
$fs = get_file_storage();
foreach ($students as [$username, $firstname, $lastname, $filename, $status]) {
    $user = $DB->get_record('user', ['username' => $username, 'deleted' => 0]);
    if (!$user) {
        $user = $generator->create_user([
            'username' => $username,
            'firstname' => $firstname,
            'lastname' => $lastname,
            'email' => $username . '@example.test',
        ]);
    }
    $generator->enrol_user($user->id, $course->id, 'student');
    $existing = $assign->get_user_submission($user->id, false);
    if ($existing && $existing->status !== ASSIGN_SUBMISSION_STATUS_NEW) {
        continue;
    }
    $path = $filesdir . '/' . $filename;
    if (!is_file($path)) {
        cli_error("нет файла работы $path");
    }
    \core\session\manager::set_user($user);
    $draftid = file_get_unused_draft_itemid();
    $fs->create_file_from_pathname((object) [
        'itemid' => $draftid,
        'contextid' => context_user::instance($user->id)->id,
        'component' => 'user',
        'filearea' => 'draft',
        'filepath' => '/',
        'filename' => $filename,
    ], $path);
    $notices = [];
    $data = (object) ['userid' => $user->id, 'files_filemanager' => $draftid];
    if (!$assign->save_submission($data, $notices)) {
        cli_error("работа $username не сохранилась: " . implode('; ', $notices));
    }
    if ($status === ASSIGN_SUBMISSION_STATUS_SUBMITTED) {
        $submission = $assign->get_user_submission($user->id, false);
        $submission->status = ASSIGN_SUBMISSION_STATUS_SUBMITTED;
        $DB->update_record('assign_submission', $submission);
    }
    \core\session\manager::set_user(get_admin());
}

// --- Токен: один постоянный на пользователя платформы ---
$token = $DB->get_field('external_tokens', 'token', [
    'userid' => $reader->id,
    'externalserviceid' => $service->id,
    'tokentype' => EXTERNAL_TOKEN_PERMANENT,
]);
if (!$token) {
    $token = \core_external\util::generate_token(
        EXTERNAL_TOKEN_PERMANENT,
        $service,
        $reader->id,
        $system,
        0,
        '',
        'platform'
    );
}

echo json_encode([
    'url' => $CFG->wwwroot,
    'course_id' => (int) $course->id,
    'assignment_id' => (int) $assignment->id,
    'token' => $token,
], JSON_UNESCAPED_UNICODE), PHP_EOL;
