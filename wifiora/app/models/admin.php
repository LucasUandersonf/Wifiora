<?php
require_once __DIR__ . '/../../config/config.php';

class Admin {
    private $conn;

    public function __construct() {
        $db = new Database();
        $this->conn = $db->conn;
    }

    public function getAll() {
        return $this->conn->query("SELECT id, email FROM admins");
    }

    public function findById($id) {
        $stmt = $this->conn->prepare("SELECT id, email FROM admins WHERE id = ?");
        $stmt->bind_param("i", $id);
        $stmt->execute();
        $admin = $stmt->get_result()->fetch_assoc();
        $stmt->close();
        return $admin;
    }

    public function create($email, $password) {
        $hashed = password_hash($password, PASSWORD_DEFAULT);
        $stmt = $this->conn->prepare("INSERT INTO admins (email, password) VALUES (?, ?)");
        $stmt->bind_param("ss", $email, $hashed);
        $stmt->execute();
        $stmt->close();
    }

    public function update($id, $email, $password = null) {
        if ($password) {
            $hashed = password_hash($password, PASSWORD_DEFAULT);
            $stmt = $this->conn->prepare("UPDATE admins SET email = ?, password = ? WHERE id = ?");
            $stmt->bind_param("ssi", $email, $hashed, $id);
        } else {
            $stmt = $this->conn->prepare("UPDATE admins SET email = ? WHERE id = ?");
            $stmt->bind_param("si", $email, $id);
        }
        $stmt->execute();
        $stmt->close();
    }

    public function delete($id) {
        $stmt = $this->conn->prepare("DELETE FROM admins WHERE id = ?");
        $stmt->bind_param("i", $id);
        $stmt->execute();
        $stmt->close();
    }

    public function login($email, $password) {
       
        $id = null;
        $hashed_password = null;

        $stmt = $this->conn->prepare("SELECT id, password FROM admins WHERE email = ?");
        $stmt->bind_param("s", $email);
        $stmt->execute();
        $stmt->store_result();
        $stmt->bind_result($id, $hashed_password);
        $stmt->fetch();

        $authenticated = false;
        if ($stmt->num_rows === 1 && password_verify($password, $hashed_password)) {
            $authenticated = true;
        }

        $stmt->close();
        return $authenticated ? $id : false;
    }
}
