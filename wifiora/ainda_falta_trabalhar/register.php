<?php
require_once 'config.php';

// Verificar se o formulário foi enviado
if ($_SERVER["REQUEST_METHOD"] == "POST") {
    $name = trim($_POST['name']);
    $email = trim($_POST['email']);
    $cpf = trim($_POST['cpf']);
    $user_type = $_POST['user_type'];
    $birth_date = $_POST['birth_date'];
    $password = $_POST['password'];
    
    // Validações básicas
    if (empty($name) || empty($email) || empty($cpf) || empty($user_type) || empty($birth_date) || empty($password)) {
        header("Location: register.html?error=campos_obrigatorios");
        exit();
    }
    
    // Verificar se email já existe
    $stmt = $conn->prepare("SELECT id FROM usuarios WHERE email = ?");
    $stmt->bind_param("s", $email);
    $stmt->execute();
    $result = $stmt->get_result();
    
    if ($result->num_rows > 0) {
        $stmt->close();
        header("Location: register.html?error=email_existe");
        exit();
    }
    $stmt->close();
    
    // Verificar se CPF já existe
    $stmt = $conn->prepare("SELECT id FROM usuarios WHERE cpf = ?");
    $stmt->bind_param("s", $cpf);
    $stmt->execute();
    $result = $stmt->get_result();
    
    if ($result->num_rows > 0) {
        $stmt->close();
        header("Location: register.html?error=cpf_existe");
        exit();
    }
    $stmt->close();
    
    // Hash da senha
    $hashed_password = password_hash($password, PASSWORD_DEFAULT);
    
    // Inserir usuário
    $stmt = $conn->prepare("INSERT INTO usuarios (name, email, cpf, user_type, birth_date, password) VALUES (?, ?, ?, ?, ?, ?)");
    $stmt->bind_param("ssssss", $name, $email, $cpf, $user_type, $birth_date, $hashed_password);
    
    if ($stmt->execute()) {
        $stmt->close();
        header("Location: success.html");
        exit();
    } else {
        $stmt->close();
        header("Location: register.html?error=erro_cadastro");
        exit();
    }
}

$conn->close();
?>

