<?php
session_start();
require_once 'config.php';

// Verificar se o formulário foi enviado
if ($_SERVER["REQUEST_METHOD"] == "POST") {
    $cpf = trim($_POST['cpf']);
    $password = $_POST['password'];
    
    // Validações básicas
    if (empty($cpf) || empty($password)) {
        header("Location: login.html?error=campos_obrigatorios");
        exit();
    }
    
    // Buscar usuário pelo CPF
    $stmt = $conn->prepare("SELECT id, name, email, password FROM usuarios WHERE cpf = ?");
    $stmt->bind_param("s", $cpf);
    $stmt->execute();
    $result = $stmt->get_result();
    
    if ($result->num_rows == 1) {
        $user = $result->fetch_assoc();
        
        // Verificar senha
        if (password_verify($password, $user['password'])) {
            // Login bem-sucedido
            $_SESSION['user_id'] = $user['id'];
            $_SESSION['user_name'] = $user['name'];
            $_SESSION['user_email'] = $user['email'];
            $_SESSION['logged_in'] = true;
            
            $stmt->close();
            header("Location: success.html");
            exit();
        } else {
            $stmt->close();
            header("Location: login.html?error=senha_incorreta");
            exit();
        }
    } else {
        $stmt->close();
        header("Location: login.html?error=usuario_nao_encontrado");
        exit();
    }
}

$conn->close();
?>

