from sqlmodel import Session, select

from app.models.scheduling import (
    Availability,
    DAYS_OF_WEEK,
    Employee,
    EmployeeRole,
    Role,
    ScheduleRule,
    SHIFT_TYPES,
)


def seed_db(session: Session) -> None:
    if session.exec(select(Role)).first():
        return

    roles = [
        Role(name="Cook"),
        Role(name="Dishwasher"),
        Role(name="Server"),
        Role(name="Manager"),
    ]
    session.add_all(roles)

    employees = [
        Employee(name="Ana Silva", max_weekly_hours=40),
        Employee(name="Bruno Costa", max_weekly_hours=40),
        Employee(name="Camila Rocha", max_weekly_hours=32),
        Employee(name="Diego Ramos", max_weekly_hours=36),
        Employee(name="Elisa Lima", max_weekly_hours=30),
        Employee(name="Felipe Alves", max_weekly_hours=40),
        Employee(name="Giovana Moura", max_weekly_hours=28),
        Employee(name="Henrique Souza", max_weekly_hours=40),
        Employee(name="Isabela Torres", max_weekly_hours=24),
        Employee(name="Joao Mendes", max_weekly_hours=40),
        Employee(name="Karina Araujo", max_weekly_hours=35),
        Employee(name="Lucas Pereira", max_weekly_hours=30),
    ]
    session.add_all(employees)
    session.commit()

    role_by_name = {role.name: role for role in session.exec(select(Role)).all()}
    employee_by_name = {
        employee.name: employee for employee in session.exec(select(Employee)).all()
    }

    role_assignments = {
        "Cook": ["Ana Silva", "Bruno Costa", "Diego Ramos"],
        "Dishwasher": ["Camila Rocha", "Giovana Moura"],
        "Server": [
            "Elisa Lima",
            "Felipe Alves",
            "Henrique Souza",
            "Isabela Torres",
        ],
        "Manager": ["Joao Mendes", "Karina Araujo"],
    }

    for role_name, employee_names in role_assignments.items():
        role = role_by_name.get(role_name)
        if not role:
            continue
        for employee_name in employee_names:
            employee = employee_by_name.get(employee_name)
            if not employee:
                continue
            session.add(
                EmployeeRole(employee_id=employee.id, role_id=role.id)
            )
    session.commit()

    weekend_blocked = {"Giovana Moura", "Isabela Torres"}
    dinner_blocked = {"Camila Rocha", "Henrique Souza"}

    for employee in employee_by_name.values():
        for day in DAYS_OF_WEEK:
            for shift in SHIFT_TYPES:
                is_available = True
                if employee.name in weekend_blocked and day in {"SATURDAY", "SUNDAY"}:
                    is_available = False
                if employee.name in dinner_blocked and shift == "DINNER":
                    is_available = False
                session.add(
                    Availability(
                        employee_id=employee.id,
                        day_of_week=day,
                        shift_type=shift,
                        is_available=is_available,
                    )
                )
    session.commit()

    weekday_needs = {
        "Cook": {"LUNCH": 2, "DINNER": 2},
        "Dishwasher": {"LUNCH": 1, "DINNER": 1},
        "Server": {"LUNCH": 3, "DINNER": 3},
        "Manager": {"LUNCH": 1, "DINNER": 1},
    }

    weekend_needs = {
        "Cook": {"LUNCH": 3, "DINNER": 2},
        "Dishwasher": {"LUNCH": 2, "DINNER": 2},
        "Server": {"LUNCH": 5, "DINNER": 4},
        "Manager": {"LUNCH": 1, "DINNER": 1},
    }

    for day in DAYS_OF_WEEK:
        needs = weekend_needs if day in {"SATURDAY", "SUNDAY"} else weekday_needs
        for shift in SHIFT_TYPES:
            for role_name, counts in needs.items():
                role = role_by_name.get(role_name)
                if not role:
                    continue
                session.add(
                    ScheduleRule(
                        day_of_week=day,
                        shift_type=shift,
                        role_id=role.id,
                        required_count=counts[shift],
                    )
                )
    session.commit()
