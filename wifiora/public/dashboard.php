<?php
require_once __DIR__ . '/../app/Controllers/DashboardController.php';

$dashboard = new DashboardController();
$dashboard->index();