<?php
require_once __DIR__ . '/../../config/config.php';

class Visitor
{
    private $conn;

    public function __construct()
    {
        $db = new Database();
        $this->conn = $db->conn;
    }
    public function getConn()
    {
        return $this->conn;
    }

    public function create($name, $cpf, $email, $password)
    {
        $hashed = password_hash($password, PASSWORD_DEFAULT);
        $stmt = $this->conn->prepare("INSERT INTO usuarios (name, cpf, email, password) VALUES (?, ?, ?, ?)");
        $stmt->bind_param("ssss", $name, $cpf, $email, $hashed);
        $result = $stmt->execute();
        $stmt->close();
        return $result;
    }

    public function getAll($search = null)
    {
        $query = "SELECT * FROM usuarios";
        if ($search) {
            $search = $this->conn->real_escape_string($search);
            $query .= " WHERE name LIKE '%$search%' OR email LIKE '%$search%' OR cpf LIKE '%$search%'";
        }
        return $this->conn->query($query);
    }

    public function findById($id)
    {
        $stmt = $this->conn->prepare("SELECT * FROM usuarios WHERE id = ?");
        $stmt->bind_param("i", $id);
        $stmt->execute();
        $visitor = $stmt->get_result()->fetch_assoc();
        $stmt->close();
        return $visitor;
    }

    public function update($id, $email, $password = null)
    {
        $sql = "UPDATE usuarios SET email = ?";
        $params = [$email];

        if ($password) {
            $hashed = password_hash($password, PASSWORD_BCRYPT);
            $sql .= ", password = ?";
            $params[] = $hashed;
        }

        $sql .= " WHERE id = ?";
        $params[] = $id;

        $stmt = $this->conn->prepare($sql);
        if ($password) {
            $stmt->bind_param("ssi", ...$params);
        } else {
            $stmt->bind_param("si", ...$params);
        }
        $stmt->execute();
        $stmt->close();
    }

    public function delete($id)
    {
        $stmt = $this->conn->prepare("DELETE FROM usuarios WHERE id = ?");
        $stmt->bind_param("i", $id);
        $stmt->execute();
        $stmt->close();
    }




}