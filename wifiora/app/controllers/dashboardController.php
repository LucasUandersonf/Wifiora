<?php
require_once __DIR__ . '/../Models/Visitor.php';

class DashboardController {
    private $visitorModel;

    public function __construct() {
        $this->visitorModel = new Visitor();
        session_start();
        if (!isset($_SESSION['admin_logged_in'])) {
            header("Location: /login.php");
            exit();
        }
    }

    public function index() {
        $conn = $this->visitorModel->getConn();

        $online_count = $conn->query("SELECT COUNT(*) as online_count FROM visitantes WHERE status='online'")->fetch_assoc()['online_count'];
        $registered_count = $conn->query("SELECT COUNT(*) as registered_count FROM usuarios")->fetch_assoc()['registered_count'];
        $today_visits_count = $conn->query("SELECT COUNT(*) as today_visits_count FROM visitas WHERE DATE(data) = CURDATE()")->fetch_assoc()['today_visits_count'];
        $access_points_count = $conn->query("SELECT COUNT(*) as access_points_count FROM pontos_acesso")->fetch_assoc()['access_points_count'];

        require  __DIR__ . '/../Views/dashboard/index.php';
    }
}