<?php
require_once __DIR__ . '/../app/Controllers/AdminController.php';

$adminController = new AdminController();

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $adminController->create($_POST);
} else {
    $adminController->create();
}