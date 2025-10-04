<?php
require_once __DIR__ . '/../Models/Visitor.php';
require_once __DIR__ . '/../Services/UnifiService.php';


class UserAuthController
{
    private $visitor;

    public function __construct()
    {
        $this->visitor = new Visitor();
        session_start();
    }

    public function login_user($data = [])
    {
        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            $email = trim($data['email']);
            $password = $data['password'];

            $user = $this->visitor->getAll();
            $found = false;

            foreach ($user as $u) {
                if ($u['email'] === $email && password_verify($password, $u['password'])) {
                    $found = $u;
                    break;
                }
            }

            if ($found) {
                $_SESSION['user_id'] = $found['id'];
                $_SESSION['user_name'] = $found['name'];
                $_SESSION['user_email'] = $found['email'];
                $_SESSION['user_logged_in'] = true;

                // Captura o MAC address do hotspot
                $mac = isset($_GET['id']) ? $_GET['id'] : null;

                if ($mac) {
                    try {
                        $unifi = new UnifiService();
                        $unifi->login();
                        $unifi->authorize($mac); // autoriza por 60 minutos
                    } catch (Exception $e) {
                        error_log("Erro ao liberar no Unifi: " . $e->getMessage());
                    }
                }

                header("Location: /success.php");
                exit();
            } else {
                $error = "E-mail ou senha incorretos!";
                require __DIR__ . '/../Views/auth/user/login_user.php';
            }
        } else {
            require __DIR__ . '/../Views/auth/user/login_user.php';
        }
    }

    public function register($data = [])
    {
        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            $name = trim($data['name']);
            $cpf = trim($data['cpf']);
            $email = trim($data['email']);
            $password = $data['password'];
            $user_type = trim($data['user_type']);
            $birth_date = $data['birth_date'];

            if ($this->visitor->create($name, $cpf, $email, $password, $user_type, $birth_date)) {
                header("Location: /login_user.php?success=1");
                exit();
            } else {
                $error = "Erro ao registrar usuário!";
                require __DIR__ . '/../Views/auth/user/register.php';
            }
        } else {
            require __DIR__ . '/../Views/auth/user/register.php';
        }
    }
}