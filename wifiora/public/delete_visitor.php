<?php
require_once __DIR__ . '/../app/Controllers/VisitorController.php';

$visitorController = new VisitorController();

if (isset($_GET['id'])) {
    $visitorController->delete($_GET['id']);
} else {
    header("Location: /public/visitantes.php");
    exit();
}