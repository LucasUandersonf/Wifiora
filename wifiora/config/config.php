<?php
//preciso adicionar no .env
class Database {
    private $host = "localhost";
    private $user = "root";
    private $pass = "";
    private $dbname = "portal_db";
    public $conn;

    public function __construct() {
        $this->conn = new mysqli($this->host, $this->user, $this->pass, $this->dbname);
        if ($this->conn->connect_error) {
            die("Conexão falhou: " . $this->conn->connect_error);
        }
        $this->conn->set_charset("utf8");
    }
}