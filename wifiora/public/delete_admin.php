<?php
require_once __DIR__ . '/../app/Controllers/AdminController.php';

$adminController = new AdminController();

if (isset($_GET['id'])) {
    $adminController->delete($_GET['id']);
} else {
    header("Location: /public/administradores.php");
    exit();
}