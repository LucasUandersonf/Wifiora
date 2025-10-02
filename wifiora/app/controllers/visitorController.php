<?php
require_once __DIR__ . '/../Models/Visitor.php';

class VisitorController {
    private $model;

    public function __construct() {
        $this->model = new Visitor();
        session_start();
        if (!isset($_SESSION['admin_logged_in'])) {
            header("Location: /login.php");
            exit();
        }
    }

    public function index($search = null) {
        $visitors = $this->model->getAll($search);
        require __DIR__ . '/../Views/visitor/index.php';
    }

    public function edit($id, $post = null) {
        $visitor = $this->model->findById($id);
        if ($post) {
            $this->model->update($id, $post['email'], $post['password'] ?? null);
            header("Location: /visitantes.php");
            exit();
        }
        require __DIR__ . '/../Views/visitor/edit.php';
    }

    public function delete($id) {
        $this->model->delete($id);
        header("Location: /visitantes.php");
        exit();
    }

    public function exportCSV() {
        header('Content-Type: text/csv; charset=utf-8');
        header('Content-Disposition: attachment; filename=visitantes.csv');

        $output = fopen('php://output', 'w');
        fputcsv($output, ['ID','Nome','CPF','Email','Tipo de Usuário']);

        $result = $this->model->getAll();
        while ($row = $result->fetch_assoc()) {
            fputcsv($output, $row);
        }
        fclose($output);
        exit();
    }
}