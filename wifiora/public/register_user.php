<?php
require_once __DIR__ . '/../app/Controllers/UserAuthController.php';

$auth = new UserAuthController();
$auth->register($_POST);