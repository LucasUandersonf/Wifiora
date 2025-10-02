<?php
require_once __DIR__ . '/../app/Controllers/VisitorController.php';

$visitorController = new VisitorController();

if (!isset($_GET['id']) && !isset($_POST['id'])) {
    header("Location: /public/visitantes.php");
    exit();
}

$id = $_GET['id'] ?? $_POST['id'];

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $visitorController->edit($id, $_POST);
} else {
    $visitorController->edit($id);
}