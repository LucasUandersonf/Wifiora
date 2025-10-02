<?php
require_once __DIR__ . '/../Models/Admin.php';

class AuthController {
    private $admin;

    public function __construct() {
        $this->admin = new Admin();
        session_start();
    }

    public function login($post) {
        if (!empty($post['email']) && !empty($post['password'])) {
            $id = $this->admin->login($post['email'], $post['password']);
            if ($id) {
                $_SESSION['admin_logged_in'] = true;
                $_SESSION['admin_id'] = $id;
                header("Location: /dashboard.php");
                exit();
            } else {
                $error = "Email ou senha inválidos.";
            }
        } else {
            $error = "Preencha todos os campos.";
        }
        require __DIR__ . '/../Views/auth/admin/login.php';
    }

    public function logout() {
        session_destroy();
        header("Location: /login.php");
        exit();
    }
}