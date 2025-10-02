<?php
require_once __DIR__ . '/../app/Controllers/VisitorController.php';

$visitorController = new VisitorController();
$search = $_GET['search'] ?? null;
$visitorController->index($search);