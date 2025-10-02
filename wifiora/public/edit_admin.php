<?php
require_once __DIR__ . '/../app/Controllers/AdminController.php';

$adminController = new AdminController();

if (!isset($_GET['id']) && !isset($_POST['id'])) {
    header("Location: /public/administradores.php");
    exit();
}

$id = $_GET['id'] ?? $_POST['id'];

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $adminController->edit($id, $_POST);
} else {
    $adminController->edit($id);
}