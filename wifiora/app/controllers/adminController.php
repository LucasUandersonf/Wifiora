<?php
require_once __DIR__ . '/../Models/Admin.php';

class AdminController {
    private $model;

    public function __construct() {
        $this->model = new Admin();
        session_start();
        if (!isset($_SESSION['admin_logged_in'])) {
            header("Location: /login.php");
            exit();
        }
    }

    public function index() {
        $admins = $this->model->getAll();
        require __DIR__ . '/../Views/admin/index.php';
    }

    public function create($post = null) {
        if ($post) {
            $this->model->create($post['email'], $post['password']);
            header("Location: /administradores.php");
            exit();
        }
        require __DIR__ . '/../Views/admin/create.php';
    }

    public function edit($id, $post = null) {
        $admin = $this->model->findById($id);
        if ($post) {
            $this->model->update($id, $post['email'], $post['password'] ?? null);
            header("Location: /administradores.php");
            exit();
        }
        require __DIR__ . '/../Views/admin/edit.php';
    }

    public function delete($id) {
        $this->model->delete($id);
        header("Location: /administradores.php");
        exit();
    }
}