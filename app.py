from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
import pandas as pd
import os
from datetime import datetime
from calendar import month_name
from sqlalchemy import extract, func, distinct, Table, MetaData
import traceback
from db_config import SessionLocal, engine
from models import Schedule

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'supersecretkey')
app.config['UPLOAD_FOLDER'] = 'Uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'xlsx', 'xls'}

def normalize_schedule_excel(df: pd.DataFrame) -> list[dict]:
    static_cols = ["Code", "Agent Name", "Email", "Gender",
                   "Batch", "Skill", "Seniority", "Team Leader"]
    date_cols = [c for c in df.columns if c not in static_cols]

    out: list[dict] = []
    for _, r in df.iterrows():
        for dc in date_cols:
            try:
                day = pd.to_datetime(dc).date()
            except Exception:
                continue
            out.append({
                "code": str(r["Code"]),
                "agent_name": r["Agent Name"],
                "email": r["Email"],
                "gender": r["Gender"],
                "batch": r["Batch"],
                "skill": r["Skill"],
                "seniority": r["Seniority"],
                "team_leader": r["Team Leader"],
                "date": day,
                "shift": str(r[dc]) if pd.notna(r[dc]) else None,
            })
    return out

def ensure_schedules_update_table_exists(session):
    metadata = MetaData()
    metadata.reflect(bind=engine)
    if 'schedules_update' not in metadata.tables:
        schedules = metadata.tables['schedules']
        schedules_update = Table(
            'schedules_update', metadata,
            *[c.copy() for c in schedules.columns]
        )
        schedules_update.create(bind=engine)
    return metadata.tables['schedules_update']

def process_upload_to_tables(session, new_records, force_overwrite):
    schedules_update = ensure_schedules_update_table_exists(session)
    stats = {
        'schedules': {'added': 0, 'updated': 0, 'skipped': 0},
        'schedules_update': {'added': 0, 'updated': 0}
    }

    for record in new_records:
        # Process for schedules table
        existing_schedule = session.query(Schedule).filter(
            Schedule.email == record['email'],
            Schedule.date == record['date']
        ).first()

        if existing_schedule:
            if force_overwrite:
                # Explicit update of all fields
                existing_schedule.code = record['code']
                existing_schedule.agent_name = record['agent_name']
                existing_schedule.email = record['email']
                existing_schedule.gender = record['gender']
                existing_schedule.batch = record['batch']
                existing_schedule.skill = record['skill']
                existing_schedule.seniority = record['seniority']
                existing_schedule.team_leader = record['team_leader']
                existing_schedule.shift = record['shift']
                session.add(existing_schedule)  # Explicitly mark as modified
                stats['schedules']['updated'] += 1
            else:
                stats['schedules']['skipped'] += 1
        else:
            session.add(Schedule(**record))
            stats['schedules']['added'] += 1

        # Process for schedules_update table (always overwrite)
        existing_update = session.execute(
            schedules_update.select().where(
                (schedules_update.c.email == record['email']) &
                (schedules_update.c.date == record['date'])
            )
        ).first()

        if existing_update:
            session.execute(
                schedules_update.update()
                .where(
                    (schedules_update.c.email == record['email']) &
                    (schedules_update.c.date == record['date'])
                )
                .values(**record)
            )
            stats['schedules_update']['updated'] += 1
        else:
            session.execute(
                schedules_update.insert().values(**record)
            )
            stats['schedules_update']['added'] += 1

    return stats

def update_team_leader_by_email(session, new_records):
    metadata = MetaData()
    metadata.reflect(bind=engine)
    if 'schedules_update' not in metadata.tables:
        return
    
    schedules_update = metadata.tables['schedules_update']
    email_to_leader = {
        record['email']: record['team_leader']
        for record in new_records
        if record['email'] and record['team_leader']
    }
    
    for email, team_leader in email_to_leader.items():
        session.execute(
            schedules_update.update()
            .where(schedules_update.c.email == email)
            .values(team_leader=team_leader)
        )

# UI pages
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/upload-form')
def upload_form():
    return render_template('upload.html')

@app.route('/search')
def search():
    return render_template('search.html')

# API endpoints
@app.route('/api/stats')
def get_stats():
    session = SessionLocal()
    try:
        agent_count = session.query(func.count(distinct(Schedule.agent_name))).scalar()
        shift_count = session.query(func.count(Schedule.id)).scalar()
        return jsonify({
            'agent_count': agent_count,
            'shift_count': shift_count
        })
    except Exception as e:
        app.logger.error(f"Stats error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': 'Failed to load statistics'}), 500
    finally:
        session.close()

@app.route('/check-duplicates', methods=['POST'])
def check_duplicates():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
        
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Only Excel files allowed'}), 400

    try:
        df = pd.read_excel(file)
        new_records = normalize_schedule_excel(df)

        session = SessionLocal()
        existing_pairs = set(
            session.query(Schedule.email, Schedule.date).all()
        )
        session.close()

        duplicates = [rec for rec in new_records if (rec['email'], rec['date']) in existing_pairs]
        return jsonify({
            'duplicates': len(duplicates),
            'total_records': len(new_records),
            'new_records': len(new_records) - len(duplicates),
            'duplicate_pairs': [(rec['email'], str(rec['date'])) for rec in duplicates]
        }), 200
    except Exception as e:
        app.logger.error(f"Duplicate check error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': f'File processing error: {str(e)}'}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    force_overwrite = request.args.get('force') == 'true'
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
        
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Only Excel files allowed'}), 400

    try:
        df = pd.read_excel(file)
        new_records = normalize_schedule_excel(df)

        session = SessionLocal()
        stats = process_upload_to_tables(session, new_records, force_overwrite)
        update_team_leader_by_email(session, new_records)
        session.commit()

        return jsonify({
            'message': f"Processed {len(new_records)} records",
            'stats': stats,
            'details': {
                'schedules': {
                    'added': stats['schedules']['added'],
                    'updated': stats['schedules']['updated'],
                    'skipped': stats['schedules']['skipped']
                },
                'schedules_update': {
                    'added': stats['schedules_update']['added'],
                    'updated': stats['schedules_update']['updated']
                }
            }
        }), 200
    except Exception as e:
        session.rollback()
        app.logger.error(f"Upload error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500
    finally:
        session.close()

@app.route('/view-db')
def view_db():
    session = SessionLocal()
    rows = session.query(Schedule).order_by(Schedule.date).all()
    session.close()
    return render_template('view_db.html', rows=rows, table_name='schedules')

@app.route('/view-schedules-update')
def view_schedules_update():
    session = SessionLocal()
    try:
        metadata = MetaData()
        metadata.reflect(bind=engine)
        if 'schedules_update' not in metadata.tables:
            return render_template('view_schedules_update.html', 
                                rows=[], 
                                agents=[], 
                                table_name='schedules_update', 
                                message='No data available in schedules_update.')
        
        schedules_update = metadata.tables['schedules_update']
        agent_filter = request.args.get('agent', '')
        message = request.args.get('message', '')
        
        agents = session.execute(
            schedules_update.select().with_only_columns(schedules_update.c.agent_name).distinct()
        ).scalars().all()
        agents = sorted(agents)
        
        query = schedules_update.select()
        if agent_filter:
            query = query.where(schedules_update.c.agent_name == agent_filter)
        query = query.order_by(schedules_update.c.date)
        
        rows = session.execute(query).fetchall()
        return render_template('view_schedules_update.html', 
                            rows=rows, 
                            agents=agents, 
                            table_name='schedules_update', 
                            agent_filter=agent_filter, 
                            message=message)
    except Exception as e:
        app.logger.error(f"View schedules_update error: {str(e)}\n{traceback.format_exc()}")
        return render_template('view_schedules_update.html', 
                             rows=[], 
                             agents=[], 
                             table_name='schedules_update', 
                             error=f"Error loading data: {str(e)}", 
                             agent_filter=agent_filter)
    finally:
        session.close()

@app.route('/filter-options')
def filter_options():
    filt_agent = request.args.get('agent')
    filt_date = request.args.get('date')
    filt_lead = request.args.get('team_leader')
    filt_skill = request.args.get('skill')
    filt_month = request.args.get('month')

    session = SessionLocal()
    q = session.query(Schedule)

    if filt_agent:
        q = q.filter(Schedule.agent_name == filt_agent)
    if filt_date:
        try:
            q = q.filter(Schedule.date == datetime.strptime(filt_date, "%Y-%m-%d").date())
        except ValueError:
            pass
    if filt_lead:
        q = q.filter(Schedule.team_leader == filt_lead)
    if filt_skill:
        q = q.filter(Schedule.skill == filt_skill)
    if filt_month:
        try:
            month_int = int(filt_month)
            q = q.filter(extract('month', Schedule.date) == month_int)
        except ValueError:
            session.close()
            return jsonify({"error": "Bad month value"}), 400

    rows = q.all()
    session.close()

    def uniq(field):
        return sorted({getattr(r, field) for r in rows})

    months_list = sorted({r.date.month for r in rows})
    months = [{"value": m, "name": month_name[m]} for m in months_list]

    return jsonify({
        "agents": uniq("agent_name"),
        "dates": [str(d) for d in uniq("date")],
        "team_leaders": uniq("team_leader"),
        "skills": uniq("skill"),
        "months": months,
    })

@app.route('/filtered-results')
def filtered_results():
    agent = request.args.get('agent')
    date = request.args.get('date')
    lead = request.args.get('team_leader')
    skill = request.args.get('skill')
    month = request.args.get('month')
    sort = request.args.get('sort', 'agent_name')

    session = SessionLocal()
    q = session.query(Schedule)

    if agent:
        q = q.filter(Schedule.agent_name == agent)
    if date:
        try:
            q = q.filter(Schedule.date == datetime.strptime(date, "%Y-%m-%d").date())
        except ValueError:
            pass
    if lead:
        q = q.filter(Schedule.team_leader == lead)
    if skill:
        q = q.filter(Schedule.skill == skill)
    if month:
        try:
            month_int = int(month)
            q = q.filter(extract('month', Schedule.date) == month_int)
        except ValueError:
            pass

    if sort == 'shift':
        q = q.order_by(Schedule.shift, Schedule.agent_name)
    else:
        q = q.order_by(Schedule.agent_name, Schedule.date)

    rows = q.all()
    session.close()

    html = (
        "<table border='1' aria-label='Filtered schedules'>"
        "<thead><tr>"
        "<th data-sort='date'>Date</th>"
        "<th data-sort='agent_name'>Agent Name</th>"
        "<th>Skill</th>"
        "<th data-sort='shift'>Shift</th>"
        "</tr></thead><tbody>"
    )
    for r in rows:
        html += (
            f"<tr><td>{r.date}</td><td>{r.agent_name}</td>"
            f"<td>{r.skill}</td><td>{r.shift}</td></tr>"
        )
    html += "</tbody></table>"
    return html

@app.route('/delete-schedules-update', methods=['POST'])
def delete_schedules_update():
    session = SessionLocal()
    try:
        metadata = MetaData()
        metadata.reflect(bind=engine)
        if 'schedules_update' not in metadata.tables:
            return jsonify({'error': 'schedules_update table not found', 'status': 'error'}), 404
        
        agent = request.form.get('agent')
        if not agent:
            return jsonify({'error': 'Agent name is required for deletion', 'status': 'error'}), 400
        
        schedules_update = metadata.tables['schedules_update']
        delete_query = schedules_update.delete().where(schedules_update.c.agent_name == agent)
        result = session.execute(delete_query)
        session.commit()
        
        return jsonify({
            'message': f"Deleted {result.rowcount} records for agent '{agent}' from schedules_update",
            'status': 'success'
        }), 200
    except Exception as e:
        session.rollback()
        app.logger.error(f"Delete schedules_update error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': f'Deletion failed: {str(e)}', 'status': 'error'}), 500
    finally:
        session.close()

if __name__ == "__main__":
    app.run(debug=True)
